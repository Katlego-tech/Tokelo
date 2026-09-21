"""The `ocr` worker's entry point (docs/design/ocr.md §4, §7; REQ-003 to REQ-005, ADR-0007).

Two kinds of job arrive here, and the key says which:

* **a lease upload** (`uploads/{tenant}/lease/{doc}`) — read the object, check it (T030), record
  its digest, and decide page by page who reads it. A page whose words are already in the PDF is
  stored here and now, because taking a text layer costs nothing. A page that has to be rendered
  and put through Tesseract becomes **its own job**, since a 30-page scan in one invocation would
  pass Lambda's fifteen minutes (ADR-0003);
* **a page job** (`jobs/page/{doc}/{n}.json`) — read that one page and store it.

Whichever invocation makes `pages_done` equal `page_count` runs the analysis. That is a race
between invocations, and it is settled in the database: the counter moves by an atomic update
that answers the new total, and it moves only when a page was really inserted, so exactly one
caller ever sees the count arrive (`store.finished_page`).

**Everything here may happen twice.** SQS delivers at least once, so every write is either
conditional or the setting of a value to what it already holds: the digest is written once
(`record_stored`), a page is inserted once (`put_page`), a clause is keyed by its ordinal, and
the lease's counts are only initialised by the delivery that stored the object. A second
delivery walks the same path and changes nothing.

**Nothing read from a lease is logged.** The worker logs what it did, never what the lease said
(ocr.md §Threats).
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from tokelo.core import jobs, keys
from tokelo.core.health import is_health_check, unknown
from tokelo.core.jobs import Gone, Job
from tokelo.core.model import (
    AuditAction,
    DocumentKind,
    DocumentStatus,
    LeaseStatus,
    Page,
    PageSource,
)
from tokelo.core.store import Store
from tokelo.ocr import flags, intake, pages

type Event = Mapping[str, Any]

JOB_VERSION = 1  # the page job object's own version (ocr.md §6)

# S3's ways of saying the object isn't there any more — a deleted account, most likely (REQ-016).
MISSING = ("NoSuchKey", "NoSuchVersion", "404")

# What a tenant is told when every page of their file defeated the reader. Not "your lease is
# fine": a lease analysed into no flags because nothing could be read would read exactly that way.
NOTHING_READ = (
    "No page of this file could be read. A photograph taken square-on in good light, "
    "or a PDF from your landlord or agent, will work better."
)

_store: Store | None = None
_s3: Any = None


def store_for() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def s3_for() -> Any:
    """One S3 client per container. boto3 ships no types; this is the only line that knows."""
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def handler(event: Event, context: object = None) -> dict[str, Any]:
    if is_health_check(event):
        return {"ok": True}
    if "Records" not in event:
        raise unknown(event, "ocr")
    return jobs.run(event, work, store_for())


def work(job: Job) -> None:
    """One job, by the shape of its key.

    EventBridge routed this object to one of two queues on the same key, so the key is the
    authority on what it is — and a message that somehow reaches the wrong queue still does the
    right thing, or nothing at all, rather than being read as the other kind.
    """
    if job.page is not None:
        page_job(job)
    elif job.kind is DocumentKind.LEASE:
        lease_job(job)
    else:
        # Only a misconfigured rule could put this here. Raised, so it drains to the dead-letter
        # queue where an operator can see it (infrastructure.md §4).
        raise unknown({"key": job.key}, "ocr")


def lease_job(job: Job) -> None:
    """An uploaded lease: check it, record it, and set its pages going."""
    store = store_for()
    tenant_id, document_id = job.tenant_id, job.document_id
    if tenant_id is None or document_id is None:  # the key's shape guarantees both
        raise unknown({"key": job.key}, "ocr")

    body = fetched(job.bucket, job.key, job.version_id)
    try:
        accepted = intake.accept(DocumentKind.LEASE, body)
    except intake.Refused as refusal:
        # REQ-003: the tenant is told why, and the message is done with. Three more deliveries
        # would refuse it three more times and end in an alarm about a file that is simply wrong.
        store.set_document_status(
            tenant_id, document_id, DocumentStatus.FAILED, failure_reason=str(refusal)
        )
        return

    stored_now = store.record_stored(
        tenant_id, document_id, job.version_id or "", hashlib.sha256(body).hexdigest(), stamp()
    )
    if stored_now:
        # Both of these belong to the storing, which happens once however often this message is
        # delivered: the counts must not be reset under page jobs already in flight, and the
        # tenant's audit log must not collect an entry per delivery (REQ-011).
        record_upload(store, tenant_id, document_id, accepted)
        store.set_lease(tenant_id, document_id, accepted.pages, 0, LeaseStatus.READING)

    done = 0
    for number in range(1, accepted.pages + 1):
        text = text_layer(body, accepted.content_type, number)
        if text is None:
            hand_out(job, document_id, number, accepted.pages)
        elif store.put_page(
            tenant_id,
            document_id,
            Page(number=number, source=PageSource.TEXT_LAYER, text=text, readable=True),
        ):
            done = store.finished_page(tenant_id, document_id)

    if done >= accepted.pages:
        analyse(store, tenant_id, document_id, accepted.pages)


def page_job(job: Job) -> None:
    """One page of a lease, rendered and read (T029)."""
    store = store_for()
    spec = json.loads(fetched(job.bucket, job.key, job.version_id))
    lease_key = str(spec.get("s3_key", ""))
    number, page_count = int(spec["page"]), int(spec["page_count"])

    # ocr.md §Threats: a forged job, written to make the worker read another tenant's lease. The
    # key inside the job has to name the document the job claims to be for, and the document has
    # to be the one the database holds under that key.
    parsed = keys.parse(lease_key)
    if (
        parsed is None
        or parsed.tenant_id is None
        or parsed.document_id is None
        or parsed.document_id != str(spec.get("document_id", ""))
    ):
        raise ValueError(f"a page job whose lease key names something else: {job.key!r}")
    tenant_id, document_id = parsed.tenant_id, parsed.document_id

    document = store.get_document(tenant_id, document_id)
    if document is None:
        raise Gone(f"{document_id} is no longer there")
    if document.document.s3_key != lease_key:
        raise ValueError(f"a page job for a key this document doesn't have: {job.key!r}")

    body = fetched(job.bucket, lease_key, spec.get("s3_version_id"))
    read = pages.read(body, document.document.content_type, number)
    if store.put_page(
        tenant_id,
        document_id,
        Page(
            number=number,
            source=PageSource(read.source),
            text=read.text,
            readable=read.readable,
        ),
    ):
        if store.finished_page(tenant_id, document_id) >= page_count:
            analyse(store, tenant_id, document_id, page_count)


def analyse(store: Store, tenant_id: str, document_id: str, page_count: int) -> None:
    """Every page is in: join the readable ones, flag the clauses, finish the lease (T033).

    An unreadable page is joined in as an empty string rather than left out, so the clauses after
    it still know the page they start on (REQ-004). If *no* page could be read there is nothing
    to analyse, and saying so is the only honest answer.
    """
    stored = store.get_document(tenant_id, document_id)
    if stored is None:
        raise Gone(f"{document_id} is no longer there")

    read = {page.number: page for page in stored.pages if page.readable}
    text = [read[n].text if n in read else "" for n in range(1, page_count + 1)]
    if not read:
        store.set_lease_status(tenant_id, document_id, LeaseStatus.FAILED)
        store.set_document_status(
            tenant_id, document_id, DocumentStatus.FAILED, failure_reason=NOTHING_READ
        )
        return

    flags.record(store, tenant_id, document_id, flags.analyse(text))


def text_layer(document: bytes, content_type: str, number: int) -> str | None:
    """The page's own words, when the PDF carries enough of them to be worth taking, else None —
    which means somebody has to render it and read it (ADR-0009)."""
    if content_type != "application/pdf":
        return None
    layer = pages.text_layer(document, number)
    return pages.tidy(layer) if len(layer.strip()) >= pages.TEXT_LAYER_IS_REAL else None


def hand_out(job: Job, document_id: str, number: int, page_count: int) -> None:
    """Write one page job. Storing it *is* the sending: S3 tells EventBridge, and the page queue
    picks it up (ADR-0003, infrastructure.md §6). The lease is named by key and version, so the
    page that is read is the page that was uploaded, even if the object is replaced later."""
    s3_for().put_object(
        Bucket=job.bucket,
        Key=keys.page_job_key(document_id, number),
        Body=json.dumps(
            {
                "version": JOB_VERSION,
                "document_id": document_id,
                "s3_key": job.key,
                "s3_version_id": job.version_id,
                "page": number,
                "page_count": page_count,
            }
        ).encode(),
        ContentType="application/json",
    )


def record_upload(
    store: Store, tenant_id: str, document_id: str, accepted: intake.Accepted
) -> None:
    """The upload, in the tenant's audit log, under their pseudonym (REQ-011).

    A tenant's row is made on their first request and holds that pseudonym; without it there is
    nobody to file an entry under, which is what a deleted account looks like (REQ-016).
    """
    tenant = store.get_tenant(tenant_id)
    if tenant is None:
        return
    store.append_audit(
        tenant["audit_subject"],
        AuditAction.UPLOAD,
        document_id,
        {"kind": str(DocumentKind.LEASE), "pages": accepted.pages},
    )


def stamp() -> str:
    """Now, to the second, in the one format this project writes times in (domain-model.md §3)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetched(bucket: str, key: str, version_id: str | None) -> bytes:
    """An object, by its version. A version that no longer exists is `Gone`: there is nothing to
    read and nothing to mark, so the message is finished with rather than retried (REQ-016)."""
    call: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if version_id:
        call["VersionId"] = version_id
    try:
        answer = s3_for().get_object(**call)
    except ClientError as e:
        if e.response["Error"]["Code"] in MISSING:
            raise Gone(f"{key} is no longer there") from e
        raise
    body: bytes = answer["Body"].read()
    return body
