"""The spine every worker sits on (docs/design/infrastructure.md §4; REQ-017, ADR-0007).

A job starts as an object in S3. S3 tells EventBridge, a rule matches the key's shape and puts
the event on that job's queue, and Lambda hands the worker a batch of those messages. This module
is the part none of the three workers should write for itself: reading the event, reporting each
message's fate, and deciding what happens when a job can't be done.

**Failures are reported per message**, not per batch (`ReportBatchItemFailures`), so one bad
object doesn't send its batch-mates round again — they are idempotent (ADR-0007), but redoing
work costs money and time, and a batch that keeps failing as a whole never drains.

**The third failure is the last.** The queues redrive after three receives (infrastructure.md
§6), so when `ApproximateReceiveCount` says three, this is the try that decides. The document is
marked `failed` with a reason a tenant can read, and the message is *still* reported as failed —
so it lands in the dead-letter queue, where the alarm is watching. Marking it and swallowing it
would leave the operator with nothing to look at.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tokelo.core import keys
from tokelo.core.model import DocumentKind, DocumentStatus
from tokelo.core.store import Store

type Event = Mapping[str, Any]

LAST_TRY = 3  # the queues' maxReceiveCount (infra/modules/tokelo-env/events.tf)

# What a tenant is told when a job could not be done. The exception's own words are for the log:
# they name files, libraries and line numbers, and none of that is the tenant's business.
FAILED = "This file couldn't be processed. Please try uploading it again."


class NotAJob(Exception):
    """The message doesn't describe an object this project writes."""


class Gone(Exception):
    """What the job is about no longer exists — a deleted account, most likely. There is nothing
    to do and nothing to mark, so the message is finished with rather than retried (REQ-016)."""


@dataclass(frozen=True)
class Job:
    """One object created, and what its key says about it."""

    message_id: str
    bucket: str
    key: str
    version_id: str | None
    size: int
    receive_count: int
    tenant_id: str | None = None
    kind: DocumentKind | None = None
    document_id: str | None = None
    page: int | None = None

    @property
    def last_try(self) -> bool:
        """True when this is the receive that redrives to the dead-letter queue if it fails."""
        return self.receive_count >= LAST_TRY


def of(event: Event) -> list[Job]:
    """The jobs in an SQS batch. Raises NotAJob if a message isn't one, because a queue that is
    fed by one rule (infrastructure.md §6) shouldn't be carrying anything else."""
    return [_job(record) for record in event.get("Records", [])]


def run(event: Event, work: Callable[[Job], None], store: Store) -> dict[str, Any]:
    """Do each job in the batch; answer the partial batch response Lambda expects.

    `work` is the lane's own: what the `ocr`, `evidence` or `dossier` worker does with an object.
    It may raise `Gone` to say the job no longer applies, and anything else to say it failed.
    """
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        try:
            job = _job(record)
        except NotAJob:
            # Nothing can be done with it, and three more goes won't help: let it drain to the
            # dead-letter queue, where somebody can look at what put it there.
            failures.append({"itemIdentifier": str(record.get("messageId", ""))})
            continue
        try:
            work(job)
        except Gone:
            continue
        except Exception:
            if job.last_try:
                _mark_failed(store, job)
            failures.append({"itemIdentifier": job.message_id})
    return {"batchItemFailures": failures}


def _mark_failed(store: Store, job: Job) -> None:
    """Tell the tenant, if there is still something to tell them about."""
    if job.tenant_id is None or job.document_id is None:
        return  # a job object, not an upload: its document is named inside the object (T042)
    try:
        store.set_document_status(
            job.tenant_id, job.document_id, DocumentStatus.FAILED, failure_reason=FAILED
        )
    except Exception:
        # The document is gone, most likely. The message still goes to the dead-letter queue.
        return


def _job(record: Mapping[str, Any]) -> Job:
    try:
        body = json.loads(record.get("body") or "{}")
        detail = body["detail"]
        bucket = detail["bucket"]["name"]
        obj = detail["object"]
        key = obj["key"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise NotAJob(f"not an S3 event: {record.get('messageId')}") from e

    parsed = keys.parse(key)
    if parsed is None:
        raise NotAJob(f"not a key this project writes: {key!r}")

    return Job(
        message_id=str(record.get("messageId", "")),
        bucket=bucket,
        key=key,
        version_id=obj.get("version-id"),
        size=int(obj.get("size", 0)),
        receive_count=int(record.get("attributes", {}).get("ApproximateReceiveCount", 1)),
        tenant_id=parsed.tenant_id,
        kind=parsed.kind,
        document_id=parsed.document_id,
        page=parsed.page,
    )
