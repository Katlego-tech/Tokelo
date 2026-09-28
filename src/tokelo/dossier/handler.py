"""The `dossier` worker's entry point (docs/design/dossier.md §4, §5, §7; REQ-013, REQ-011).

A dossier job is an object the `api` wrote, `jobs/dossier/<dossier>.json` (api.md §6). This
worker turns it into one PDF ([pdf.py](pdf.py)), stored at `dossiers/<tenant>/<dossier>.pdf` and
recorded against the dossier: its version, digest, pages and size.

**It trusts nothing it's handed.** The job object says whose dossier it is, and nothing more is
taken from it. The documents are the ones the `Dossier` item names, in that tenant's own
partition. Each is checked again with the `api`'s own rule and words
([selection.py](selection.py)): the tenant's, and finished. Each file is read by the version its
digest was taken of, and hashed again. A file whose bytes no longer match is still put in, and
marked in red.

**Only `ready` and `failed` are finished** (dossier.md §4, §5). SQS delivers at least once:
- A delivery that finds the dossier `compiling` is a retry after a failed attempt, and builds it
  again from the start. Stopping there would leave the dossier `compiling` for good.
- Two deliveries at once may both build and store a PDF. `ready` is written only while the
  dossier is still `compiling`, so exactly one records its PDF: the version it stored, that
  version's digest, and the audit entry. The download link names that version.
- On the third failure the dossier is marked `failed`, and the message still goes to the
  dead-letter queue, as every job's does. `jobs.run` can't mark it: a job object's key names no
  tenant.

**A dossier over 100 MB is refused**, before anything is read when the files' own sizes already
say so, and after the build when the PDF does. So is one with more than 5 MB of chat, which is
what the function has the time and memory to set.
"""

import hashlib
import json
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from tokelo.core import jobs, keys
from tokelo.core.health import is_health_check, unknown
from tokelo.core.jobs import Gone, Job
from tokelo.core.model import AuditAction, Document, DocumentKind, DossierStatus
from tokelo.core.store import Store
from tokelo.dossier import pdf, selection, timeline
from tokelo.evidence import digest

type Event = Mapping[str, Any]

JOB_VERSION = 1  # api.md §6, "The dossier job request"
MEGABYTE = 1024 * 1024
LIMIT_BYTES = 100 * MEGABYTE  # dossier.md §4
# What a photograph can add to the PDF at most, once fitted at 150 dpi (pdf.picture). A 20 MB
# original doesn't make a 20 MB page.
PICTURE_BYTES = 2 * MEGABYTE
# A chat export's messages set as pages take more room than the export's own text.
TEXT_GROWTH = 3
# Setting messages is the slow part of a dossier: a 5 MB export, the most one upload may be, is
# some 43,000 messages, set twice (the timeline and the communications) in about 40 s on a
# laptop and 380 MB (T043's measurement). The function has 300 s and 1 GB on a slower CPU, so a
# dossier takes one maximum-size export's worth of chat, and no more.
CHAT_LIMIT_BYTES = 5 * MEGABYTE

TOO_MANY = (
    "Too many records for one dossier: it would pass 100 MB. Choose fewer records and build "
    "it again."
)
TOO_MUCH_CHAT = (
    "Too many chat messages for one dossier: the chosen WhatsApp exports hold more than 5 MB of "
    "text. Choose fewer exports and build it again."
)
NOT_BUILT = "This dossier couldn't be built. Please try again."
NO_LONGER_STORED = "A chosen file is no longer stored, so it can't go into a dossier."

_UUID = re.compile(rf"^{keys.UUID}$")

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
        raise unknown(event, "dossier")
    return jobs.run(event, work, store_for())


@dataclass(frozen=True)
class Request:
    """What the job object says, checked: whose dossier, and which."""

    tenant_id: str
    dossier_id: str


def work(job: Job) -> None:
    """One dossier job, start to finish."""
    dossier_id = job.document_id  # a dossier job's key names the dossier (keys.parse)
    if dossier_id is None or job.tenant_id is not None or job.page is not None:
        raise unknown({"key": job.key}, "dossier")
    request = requested(job, dossier_id)
    store = store_for()
    try:
        compile_dossier(store, request, job)
    except Gone:
        raise
    except Exception:
        if job.last_try:
            store.fail_dossier(request.tenant_id, request.dossier_id, NOT_BUILT)
        raise


def requested(job: Job, dossier_id: str) -> Request:
    """The job object, by the version the event names. Raises Gone when it is no longer there,
    and ValueError when it isn't one the `api` wrote for this dossier."""
    try:
        at = {"VersionId": job.version_id} if job.version_id else {}
        body = s3_for().get_object(Bucket=job.bucket, Key=job.key, **at)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in digest.MISSING:
            raise Gone(f"{job.key} is no longer there") from e
        raise
    asked = json.loads(body)
    tenant_id = asked.get("tenant_id") if isinstance(asked, dict) else None
    if (
        not isinstance(asked, dict)
        or asked.get("version") != JOB_VERSION
        or asked.get("dossier_id") != dossier_id
        or not isinstance(tenant_id, str)
        or not _UUID.match(tenant_id)
    ):
        raise ValueError(f"{job.key} is not a dossier job this project wrote")
    return Request(tenant_id=tenant_id, dossier_id=dossier_id)


def compile_dossier(store: Store, request: Request, job: Job) -> None:
    tenant_id, dossier_id = request.tenant_id, request.dossier_id
    dossier = store.get_dossier(tenant_id, dossier_id)
    if dossier is None:
        # No such dossier in that tenant's partition: a deleted account, or a job object that
        # names someone it shouldn't. Either way there is nothing here to build.
        raise Gone(f"dossier {dossier_id} is no longer there")
    if dossier.status in (DossierStatus.READY, DossierStatus.FAILED):
        return  # finished: a redelivery has nothing to do (ADR-0007)

    mine = {d.id: d for d in store.list_documents(tenant_id)}
    try:
        chosen = selection.chosen(dossier.document_ids)
        documents = selection.check(chosen, mine)
        if estimated(documents) > LIMIT_BYTES:
            raise selection.Refused(TOO_MANY)
        chat = sum(d.size_bytes for d in documents if d.kind is DocumentKind.CHAT)
        if chat > CHAT_LIMIT_BYTES:
            raise selection.Refused(TOO_MUCH_CHAT)
    except selection.Refused as refusal:
        store.fail_dossier(tenant_id, dossier_id, str(refusal))
        return
    if not store.start_dossier(tenant_id, dossier_id):
        return  # another delivery finished it in the meantime

    try:
        records = [record(store, tenant_id, document, job.bucket) for document in documents]
    except NoLongerStored:
        store.fail_dossier(tenant_id, dossier_id, NO_LONGER_STORED)
        return
    wanted = set(chosen)
    entries = [e for e in store.list_timeline(tenant_id) if e.document_id in wanted]

    key = keys.dossier_key(tenant_id, dossier_id)
    with tempfile.TemporaryDirectory() as folder:  # /tmp, which the function has 2 GB of
        path = Path(folder) / "dossier.pdf"
        with path.open("wb") as out:
            built = pdf.build(dossier_id, records, entries, _now(), out)
        size = path.stat().st_size
        if size > LIMIT_BYTES:
            store.fail_dossier(tenant_id, dossier_id, TOO_MANY)
            return
        sha256 = _sha256(path)
        with path.open("rb") as body:
            put = s3_for().put_object(
                Bucket=job.bucket, Key=key, Body=body, ContentType="application/pdf"
            )
    version = put.get("VersionId")
    if not version:
        # The link must name the version the digest describes (dossier.md §4); an unversioned
        # bucket has none to name, and a dossier recorded without one could be swapped.
        raise RuntimeError("the documents bucket gave no version: is versioning on?")

    made_ready = store.finish_dossier(
        tenant_id,
        dossier_id,
        s3_key=key,
        s3_version_id=version,
        sha256=sha256,
        page_count=built.page_count,
        size_bytes=size,
        ready_at=_now(),
    )
    if made_ready:
        audit(store, tenant_id, dossier_id, sha256, len(documents), built.page_count)


def estimated(documents: list[Document]) -> int:
    """What the chosen files would add to the PDF, from their own recorded sizes: a PDF's pages
    as they are, a photograph fitted, an export's text set as pages. Enough to refuse a dossier
    that could only pass 100 MB before a byte of it is read."""
    total = 0
    for document in documents:
        if document.content_type == "application/pdf":
            total += document.size_bytes
        elif document.kind is DocumentKind.CHAT:
            total += document.size_bytes * TEXT_GROWTH
        else:
            total += min(document.size_bytes, PICTURE_BYTES)
    return total


class NoLongerStored(Exception):
    """The version a digest was taken of can't be read any more."""


def record(store: Store, tenant_id: str, document: Document, bucket: str) -> pdf.Record:
    """One chosen document as the dossier shows it, read by its recorded version and hashed
    again. A photograph is fitted as soon as it's read, so its original is never held beside the
    others."""
    try:
        body = (
            s3_for()
            .get_object(Bucket=bucket, Key=document.s3_key, VersionId=document.s3_version_id)[
                "Body"
            ]
            .read()
        )
    except ClientError as e:
        if e.response["Error"]["Code"] in digest.MISSING:
            raise NoLongerStored(document.id) from e
        raise
    matches = hashlib.sha256(body).hexdigest() == document.sha256
    is_pdf = document.content_type == "application/pdf"

    if document.kind is DocumentKind.CHAT:
        text = body.decode("utf-8-sig", errors="replace")
        return pdf.Record(document, matches, messages=tuple(timeline.messages(text)))
    if document.kind is DocumentKind.LEASE:
        stored = store.get_document(tenant_id, document.id)
        clauses = tuple(stored.clauses) if stored else ()
        unreadable = (
            tuple(sorted(p.number for p in stored.pages if not p.readable)) if stored else ()
        )
        return pdf.Record(
            document,
            matches,
            pdf=body if is_pdf else None,
            picture=None if is_pdf else pdf.picture(body),
            clauses=clauses,
            unreadable_pages=unreadable,
        )
    if document.kind is DocumentKind.NOTICE and is_pdf:
        return pdf.Record(document, matches, pdf=body)
    return pdf.Record(document, matches, picture=pdf.picture(body))


def audit(
    store: Store, tenant_id: str, dossier_id: str, sha256: str, documents: int, pages: int
) -> None:
    """The dossier, in the tenant's audit log under their pseudonym (REQ-011): which PDF, of how
    many records. Without the tenant's row there is nobody to file it under (REQ-016)."""
    tenant = store.get_tenant(tenant_id)
    if tenant is None:
        return
    store.append_audit(
        tenant["audit_subject"],
        AuditAction.DOSSIER,
        dossier_id,
        {"sha256": sha256, "documents": documents, "page_count": pages},
    )


def _sha256(path: Path) -> str:
    taken = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(digest.CHUNK), b""):
            taken.update(chunk)
    return taken.hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
