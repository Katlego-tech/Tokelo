"""The `ocr` worker, from an object in S3 to a lease with flags (T057; ocr.md §4, §6).

Everything the lane needs was built before this: the intake (T030), the reader (T029), the
splitter (T031), the catalogue (T032) and the flags (T033). What is held here is the wiring —
which invocation does what, and what happens when the same message arrives twice.

**The bucket is a stub; the database is real.** DynamoDB Local runs the conditional writes and
the atomic counter exactly as staging does, and those are what the fan-out's correctness rests
on. S3 is a dictionary, because what matters about it here is only which objects appear in it.

**Tesseract is not exercised here.** The reader was measured against NFR-005 inside the `ocr`
image, where Tesseract is (tests/ocr/test_accuracy.py); the digital sample lease reaches the same
`pages.read` through the same page job and comes back from the PDF's text layer, which is the
route this test needs and the one a lease from an agent takes anyway (ADR-0009).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from tokelo.core import keys
from tokelo.core.model import (
    AuditAction,
    Document,
    DocumentKind,
    DocumentStatus,
    LeaseStatus,
)
from tokelo.ocr import handler

LEASES = Path(__file__).resolve().parents[1] / "fixtures" / "leases"
TENANT = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
BUCKET = "tokelo-test-documents-000000000000"
LEASE_KEY = keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT)


class Bucket:
    """S3, as far as this worker can tell: objects by key, and a version on each."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.versions: dict[str, str] = {}

    def put(self, key: str, body: bytes, version: str = "v1") -> None:
        self.objects[key] = body
        self.versions[key] = version

    # the two calls the worker makes, spelt as boto3 spells them
    def get_object(self, Bucket: str, Key: str, VersionId: str | None = None) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects or (VersionId and VersionId != self.versions[Key]):
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
                "GetObject",
            )
        body = self.objects[Key]
        return {"Body": type("Body", (), {"read": staticmethod(lambda: body)})()}

    def put_object(self, **call: Any) -> dict[str, Any]:
        body = call["Body"]
        self.put(call["Key"], body if isinstance(body, bytes) else bytes(body))
        return {}

    def page_jobs(self) -> list[str]:
        return sorted(k for k in self.objects if k.startswith("jobs/page/"))


@pytest.fixture
def bucket(monkeypatch) -> Bucket:
    stub = Bucket()
    monkeypatch.setattr(handler, "s3_for", lambda: stub)
    return stub


@pytest.fixture
def worker(store, bucket, monkeypatch):
    """The handler, with the real store and the stubbed bucket."""
    monkeypatch.setattr(handler, "store_for", lambda: store)
    return handler.handler


@pytest.fixture
def uploaded(store, bucket):
    """A tenant who has asked to upload a lease, and the file now in the bucket."""

    def upload(name: str = "digital.pdf", content_type: str = "application/pdf") -> bytes:
        body = (LEASES / name).read_bytes() if (LEASES / name).exists() else name.encode()
        subject = store.create_tenant(TENANT, created_at="2026-09-21T08:00:00Z")
        store.create_document(
            TENANT,
            Document(
                id=DOCUMENT,
                kind=DocumentKind.LEASE,
                status=DocumentStatus.REQUESTED,
                s3_key=LEASE_KEY,
                content_type=content_type,
                size_bytes=len(body),
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        bucket.put(LEASE_KEY, body)
        upload.subject = subject  # type: ignore[attr-defined]
        return body

    return upload


def record(key: str, *, receives: int = 1, message_id: str = "m1", version: str = "v1") -> dict:
    """One SQS record carrying an EventBridge Object Created, as Lambda delivers it."""
    return {
        "messageId": message_id,
        "body": json.dumps(
            {
                "detail-type": "Object Created",
                "source": "aws.s3",
                "detail": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": key, "size": 2048, "version-id": version},
                },
            }
        ),
        "attributes": {"ApproximateReceiveCount": str(receives)},
        "eventSource": "aws:sqs",
    }


def batch(*records: dict) -> dict:
    return {"Records": list(records)}


@pytest.mark.req("REQ-017")
def test_the_health_check_still_answers(worker):
    assert worker({"realm": "health"}) == {"ok": True}


@pytest.mark.req("REQ-005")
def test_a_lease_that_carries_its_own_words_is_read_and_analysed_in_one_invocation(
    worker, store, bucket, uploaded
):
    """A PDF from an agent: both pages have a text layer, so no page job is needed and the lease
    job finishes the whole lease itself (ocr.md §4). What the tenant gets is flags."""
    body = uploaded()

    assert worker(batch(record(LEASE_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.PROCESSED
    assert stored.document.sha256 == hashlib.sha256(body).hexdigest()
    assert stored.document.s3_version_id == "v1"
    assert stored.document.lease is not None
    assert stored.document.lease.page_count == 2
    assert stored.document.lease.pages_done == 2
    assert stored.document.lease.status is LeaseStatus.ANALYSED
    assert bucket.page_jobs() == [], "a text layer needs no page job"

    flagged = {f["rule_id"] for c in stored.clauses for f in c.flags}
    assert "eviction-without-court-order" in flagged


@pytest.mark.req("REQ-011")
def test_the_upload_is_recorded_in_the_audit_log_once(worker, store, uploaded):
    """REQ-011. The entry belongs to the storing, which happens once however often the message
    is delivered — so a redelivery cannot add a second."""
    uploaded()
    worker(batch(record(LEASE_KEY)))
    worker(batch(record(LEASE_KEY, message_id="m2")))

    entries = store.list_audit(store.get_tenant(TENANT)["audit_subject"])
    uploads = [e for e in entries if e.action is AuditAction.UPLOAD]
    assert len(uploads) == 1
    assert uploads[0].target_id == DOCUMENT


@pytest.mark.req("REQ-004")
def test_a_scan_is_fanned_out_one_job_per_page(worker, store, bucket, uploaded):
    """No text layer, so nothing can be read in this invocation: a 30-page scan would pass
    Lambda's fifteen minutes (ADR-0003), so each page becomes its own job."""
    uploaded("scanned.pdf")

    assert worker(batch(record(LEASE_KEY))) == {"batchItemFailures": []}

    assert bucket.page_jobs() == [
        keys.page_job_key(DOCUMENT, 1),
        keys.page_job_key(DOCUMENT, 2),
    ]
    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.lease is not None
    assert stored.document.lease.status is LeaseStatus.READING
    assert stored.document.lease.pages_done == 0
    assert stored.pages == [] and stored.clauses == []

    spec = json.loads(bucket.objects[keys.page_job_key(DOCUMENT, 1)])
    assert spec == {
        "version": 1,
        "document_id": DOCUMENT,
        "s3_key": LEASE_KEY,
        "s3_version_id": "v1",
        "page": 1,
        "page_count": 2,
    }


@pytest.mark.req("REQ-004")
def test_the_page_job_that_finishes_the_lease_runs_the_analysis(worker, store, bucket, uploaded):
    """ocr.md §4: whoever makes pages_done equal page_count analyses. So the first page job
    leaves the lease reading, and the second — whichever it is — finishes it."""
    uploaded()
    # The lease job would have taken the text layer itself; the jobs are written by hand here so
    # that the page-job path is what runs.
    for number in (1, 2):
        bucket.put(
            keys.page_job_key(DOCUMENT, number),
            json.dumps(
                {
                    "version": 1,
                    "document_id": DOCUMENT,
                    "s3_key": LEASE_KEY,
                    "s3_version_id": "v1",
                    "page": number,
                    "page_count": 2,
                }
            ).encode(),
        )
    store.set_lease(TENANT, DOCUMENT, 2, 0, LeaseStatus.READING)

    worker(batch(record(keys.page_job_key(DOCUMENT, 1))))
    half = store.get_document(TENANT, DOCUMENT)
    assert half is not None and half.document.lease is not None
    assert half.document.lease.pages_done == 1
    assert half.document.lease.status is LeaseStatus.READING
    assert half.clauses == []

    worker(batch(record(keys.page_job_key(DOCUMENT, 2), message_id="m2")))
    whole = store.get_document(TENANT, DOCUMENT)
    assert whole is not None and whole.document.lease is not None
    assert whole.document.lease.pages_done == 2
    assert whole.document.lease.status is LeaseStatus.ANALYSED
    assert len(whole.clauses) >= 20
    assert {p.number for p in whole.pages} == {1, 2}


@pytest.mark.req("REQ-003")
def test_a_file_that_is_not_a_lease_is_failed_with_its_reason(worker, store, bucket, uploaded):
    """REQ-003's second check (T030), now where a tenant can see it: the document fails with the
    reason, no page is read, and the message is finished with rather than retried — three more
    goes would refuse it three more times."""
    uploaded()
    bucket.put(LEASE_KEY, b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 300)

    assert worker(batch(record(LEASE_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.FAILED
    assert stored.document.failure_reason is not None
    assert "PDF" in stored.document.failure_reason
    assert bucket.page_jobs() == []


@pytest.mark.req("REQ-016")
def test_a_lease_whose_object_is_gone_is_finished_with_quietly(worker, store, uploaded):
    """A deleted account takes its objects with it (REQ-016). There is nothing to read and
    nothing to mark, so the message is done with — not retried three times into the alarm."""
    uploaded()

    assert worker(batch(record(LEASE_KEY, version="v-gone"))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.REQUESTED, "nothing was written"


@pytest.mark.req("REQ-005")
def test_the_same_lease_delivered_twice_leaves_one_lease(worker, store, uploaded):
    """ADR-0007. SQS delivers at least once. The second delivery must not double the pages, the
    clauses or the counter, or a tenant reads their lease twice over."""
    uploaded()
    worker(batch(record(LEASE_KEY)))
    once = store.get_document(TENANT, DOCUMENT)

    worker(batch(record(LEASE_KEY, message_id="m2", receives=2)))
    twice = store.get_document(TENANT, DOCUMENT)

    assert once is not None and twice is not None
    assert once.document.item() == twice.document.item()
    assert [p.item() for p in once.pages] == [p.item() for p in twice.pages]
    assert [c.item() for c in once.clauses] == [c.item() for c in twice.clauses]


@pytest.mark.req("REQ-004")
def test_a_lease_no_page_of_which_could_be_read_fails_and_says_so(
    worker, store, bucket, uploaded, monkeypatch
):
    """ocr.md §4's failure path. Tesseract found nothing on any page — a photograph taken in the
    dark. The lease fails with something a tenant can act on, rather than being analysed into no
    flags at all, which would read as "your lease is fine"."""
    from tokelo.ocr import pages

    uploaded("photo-unreadable.jpg", content_type="image/jpeg")
    monkeypatch.setattr(pages, "read", lambda *_: pages.Read(text="", source="ocr", readable=False))

    worker(batch(record(LEASE_KEY)))
    assert bucket.page_jobs() == [keys.page_job_key(DOCUMENT, 1)]
    worker(batch(record(keys.page_job_key(DOCUMENT, 1), message_id="m2")))

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.FAILED
    assert stored.document.lease is not None
    assert stored.document.lease.status is LeaseStatus.FAILED
    assert stored.document.failure_reason is not None
    assert "could" in stored.document.failure_reason
    assert stored.clauses == []


@pytest.mark.req("REQ-001")
def test_a_page_job_that_names_a_lease_its_key_does_not_match_is_refused(
    worker, store, bucket, uploaded
):
    """ocr.md §Threats: a forged page job, written to make the worker read another tenant's
    lease. Only the `ocr` role can write under `jobs/page/`, and this is the second lock: the
    key inside the job has to name the document the job is for."""
    uploaded()
    forged = keys.page_job_key(DOCUMENT, 1)
    bucket.put(
        forged,
        json.dumps(
            {
                "version": 1,
                "document_id": DOCUMENT,
                "s3_key": keys.upload_key(
                    "99999999-9999-4999-8999-999999999999",
                    DocumentKind.LEASE,
                    "88888888-8888-4888-8888-888888888888",
                ),
                "s3_version_id": "v1",
                "page": 1,
                "page_count": 1,
            }
        ).encode(),
    )

    answer = worker(batch(record(forged)))
    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None and stored.pages == []


@pytest.mark.req("REQ-017")
def test_a_message_the_ocr_worker_has_no_business_with_is_not_guessed_at(worker):
    """A dossier job on the lease queue could only be a misconfiguration. It is reported as a
    failure so it drains to the dead-letter queue, where somebody can see it."""
    answer = worker(batch(record(keys.dossier_job_key(DOCUMENT))))
    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
