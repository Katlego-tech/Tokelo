"""The `evidence` worker's entry point (docs/design/evidence.md §4, §7; REQ-008, REQ-011).

Everything a tenant uploads that isn't a lease arrives here: a photograph of the damp, a notice
from the landlord, a WhatsApp export. What this worker owes each of them is the same — a record
of what the file **is**, taken from the file itself.

The order is evidence.md §4's, and each step is there for a reason:

1. **Stop if it already has a digest.** SQS delivers at least once, and a digest that could be
   rewritten would be worth nothing (ADR-0007, REQ-008).
2. **HEAD it first.** The object's real size is the only one worth checking: the upload policy's
   limit is enforced by S3, but a client that got around it would have been believed on its own
   word otherwise (REQ-003).
3. **Hash it by version, streamed.** [digest.py](digest.py).
4. **Record it, once**, with the time storage took the file rather than the time this ran.
5. **Audit the upload**, under the tenant's pseudonym (REQ-011).

A photo's capture metadata (T038) and the timeline entries a notice or a chat export make (T041)
hang off step 4, and are not here yet.
"""

from collections.abc import Mapping
from typing import Any

import boto3
from botocore.exceptions import ClientError

from tokelo.core import jobs
from tokelo.core.health import is_health_check, unknown
from tokelo.core.jobs import Gone, Job
from tokelo.core.model import AuditAction, DocumentKind, DocumentStatus
from tokelo.core.store import Store
from tokelo.evidence import digest
from tokelo.ocr.intake import KINDS, MEGABYTE

type Event = Mapping[str, Any]

# What this worker's queue carries (infra/modules/tokelo-env/events.tf). A lease is the `ocr`
# worker's, and anything else on this queue could only be a misconfigured rule.
MINE = (DocumentKind.PHOTO, DocumentKind.NOTICE, DocumentKind.CHAT)

# S3's ways of saying the object isn't there any more — a deleted account, most likely (REQ-016).
MISSING = ("NoSuchKey", "NoSuchVersion", "404")

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
        raise unknown(event, "evidence")
    return jobs.run(event, work, store_for())


def work(job: Job) -> None:
    """One uploaded file: fingerprinted, recorded, audited."""
    store = store_for()
    kind, tenant_id, document_id = job.kind, job.tenant_id, job.document_id
    if kind is None or kind not in MINE or tenant_id is None or document_id is None:
        raise unknown({"key": job.key}, "evidence")

    document = store.get_document(tenant_id, document_id)
    if document is None:
        raise Gone(f"{document_id} is no longer there")
    if document.document.sha256:
        return  # already fingerprinted: a redelivery has nothing to do (ADR-0007)

    limit = KINDS[kind].size
    try:
        size = digest.head_size(s3_for(), job.bucket, job.key, job.version_id)
    except ClientError as e:
        raise gone_or_raise(e, job.key) from e
    if size > limit:
        # A client that got around the POST policy. The tenant is told, and the message is done
        # with: three more deliveries would refuse the same file three more times.
        store.set_document_status(
            tenant_id,
            document_id,
            DocumentStatus.FAILED,
            failure_reason=f"A {kind} may be at most {limit // MEGABYTE} MB.",
        )
        return

    try:
        taken = digest.of(s3_for(), job.bucket, job.key, job.version_id)
    except ClientError as e:
        raise gone_or_raise(e, job.key) from e

    first = store.record_stored(
        tenant_id, document_id, job.version_id or "", taken.sha256, taken.stored_at
    )
    if first:
        record_upload(store, tenant_id, document_id, kind, taken)
    store.set_document_status(tenant_id, document_id, DocumentStatus.PROCESSED)


def record_upload(
    store: Store, tenant_id: str, document_id: str, kind: DocumentKind, taken: digest.Taken
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
        {"kind": str(kind), "sha256": taken.sha256, "size_bytes": taken.size},
    )


def gone_or_raise(error: ClientError, key: str) -> Exception:
    """An object that isn't there any more is `Gone` — nothing to hash, nothing to mark, and
    nothing three more deliveries would fix (REQ-016). Anything else is a real failure."""
    if error.response["Error"]["Code"] in MISSING:
        return Gone(f"{key} is no longer there")
    return error
