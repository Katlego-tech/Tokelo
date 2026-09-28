"""The `dossier` worker: a job object in, a stored and recorded PDF out (REQ-013, REQ-011;
docs/design/dossier.md §4, §5).

What it owes, beyond a PDF:
- **It trusts nothing it is handed.** The documents are the ones the `Dossier` item names, in the
  tenant's partition, and each is checked again, whatever the job object lists.
- **Only `ready` and `failed` are finished.** A retry after a failed attempt builds again; a
  redelivered finished job does nothing.
- **`ready` is recorded once.** It records the version it describes, so two deliveries at once
  can't leave a digest describing the other one's file. The audit entry is written by the one
  that recorded it.
- **The third failure says so:** the dossier is `failed`, and the message still goes to the
  dead-letter queue.

The store is DynamoDB Local; S3 is tests/fakes.py's versioned bucket.
"""

import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from pypdf import PdfReader

from fakes import Bucket, batch, s3_record
from tokelo.core import keys
from tokelo.core.model import (
    AuditAction,
    Capture,
    Clause,
    Document,
    DocumentKind,
    DocumentStatus,
    Dossier,
    DossierStatus,
    LeaseStatus,
    TimelineEntry,
    TimelineSource,
)
from tokelo.dossier import handler, pdf, selection, timeline
from tokelo.ocr import flags, rules

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
BUCKET = "tokelo-test-documents-000000000000"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LEASE = (FIXTURES / "leases" / "digital.pdf").read_bytes()
PHOTO = (FIXTURES / "photos" / "damp-full.jpg").read_bytes()
EXPORT = (FIXTURES / "timeline" / "android.txt").read_bytes()


class Throttled(Bucket):
    """A bucket that refuses the next `failures` reads of a document: throttled, then fine."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def get_object(self, Bucket: str, Key: str, VersionId: str | None = None) -> dict[str, Any]:  # noqa: N803
        if Key.startswith("uploads/") and self.failures > 0:
            self.failures -= 1
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "slow"}}, "GetObject")
        return super().get_object(Bucket=Bucket, Key=Key, VersionId=VersionId)


@pytest.fixture
def bucket() -> Bucket:
    return Bucket()


@pytest.fixture
def worker(store, bucket, monkeypatch):
    monkeypatch.setattr(handler, "store_for", lambda: store)
    monkeypatch.setattr(handler, "s3_for", lambda: bucket)
    store.create_tenant(TENANT, created_at="2026-09-01T08:00:00Z")
    return handler.handler


def upload(
    store,
    bucket: Bucket,
    kind: DocumentKind,
    body: bytes,
    content_type: str,
    tenant: str = TENANT,
    capture: Capture | None = None,
) -> str:
    """A document as its worker leaves it: stored by version, fingerprinted, `processed`."""
    document_id = str(uuid.uuid4())
    key = keys.upload_key(tenant, kind, document_id)
    store.create_document(
        tenant,
        Document(
            id=document_id,
            kind=kind,
            status=DocumentStatus.REQUESTED,
            s3_key=key,
            content_type=content_type,
            size_bytes=len(body),
            requested_at="2026-09-21T08:00:00Z",
        ),
    )
    bucket.put(key, body, version="v1")
    store.record_stored(
        tenant, document_id, "v1", hashlib.sha256(body).hexdigest(), "2026-09-21T08:30:00Z"
    )
    if capture is not None:
        store.set_capture(tenant, document_id, capture)
    if kind is DocumentKind.LEASE:
        catalogue = rules.catalogue()
        rule = next(r for r in catalogue.rules if r.id == "deposit-no-interest")
        store.set_lease(tenant, document_id, 2, 2, LeaseStatus.READING)
        flags.record(
            store,
            tenant,
            document_id,
            [
                Clause(
                    ordinal=1,
                    label="5",
                    first_page=1,
                    text="The deposit shall not earn interest.",
                    flags=[flags.flag(rule, catalogue.version)],
                )
            ],
        )
    else:
        store.set_document_status(tenant, document_id, DocumentStatus.PROCESSED)
    return document_id


@pytest.fixture
def selected(store, bucket):
    """A lease, a photograph and an export, with the photo's and the export's timeline entries."""
    lease = upload(store, bucket, DocumentKind.LEASE, LEASE, "application/pdf")
    photo = upload(
        store,
        bucket,
        DocumentKind.PHOTO,
        PHOTO,
        "image/jpeg",
        capture=Capture(captured_at="2026-03-01T18:04:22+02:00", device="Samsung SM-A536B"),
    )
    export = upload(store, bucket, DocumentKind.CHAT, EXPORT, "text/plain")
    store.add_timeline_entry(
        TENANT,
        TimelineEntry(
            id=photo,
            occurred_at="2026-03-01T16:04:22Z",
            source=TimelineSource.CAPTURE,
            summary="Photograph taken",
            document_id=photo,
        ),
    )
    store.add_timeline_entries(TENANT, timeline.chat_entries(export, EXPORT))
    return [lease, photo, export]


def ask(store, bucket: Bucket, document_ids: list[str], listed: list[str] | None = None) -> str:
    """What the `api` does (T042): the Dossier, `requested`, and its job object. `listed` is what
    the job object claims, when a test wants it to differ from the dossier."""
    dossier_id = str(uuid.uuid4())
    store.create_dossier(
        TENANT,
        Dossier(
            id=dossier_id,
            status=DossierStatus.REQUESTED,
            document_ids=document_ids,
            requested_at="2026-10-01T09:00:00Z",
        ),
    )
    job = {
        "version": 1,
        "dossier_id": dossier_id,
        "tenant_id": TENANT,
        "document_ids": listed if listed is not None else document_ids,
        "requested_at": "2026-10-01T09:00:00Z",
    }
    bucket.put(keys.dossier_job_key(dossier_id), json.dumps(job).encode())
    return dossier_id


def delivered(dossier_id: str, receives: int = 1) -> dict:
    return batch(
        s3_record(
            keys.dossier_job_key(dossier_id), bucket=BUCKET, receives=receives, message_id="m1"
        )
    )


def audited(store) -> list:
    subject = store.get_tenant(TENANT)["audit_subject"]
    return [e for e in store.list_audit(subject) if e.action is AuditAction.DOSSIER]


# ----------------------------------------------------------- the whole way ---
@pytest.mark.req("REQ-013", "REQ-011")
def test_a_requested_dossier_is_built_stored_and_recorded(worker, store, bucket, selected):
    dossier_id = ask(store, bucket, selected)

    answer = worker(delivered(dossier_id))

    assert answer == {"batchItemFailures": []}
    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.READY
    key = keys.dossier_key(TENANT, dossier_id)
    assert dossier.s3_key == key
    stored = bucket.history[(key, dossier.s3_version_id or "")]
    assert dossier.sha256 == hashlib.sha256(stored).hexdigest()
    assert dossier.size_bytes == len(stored)
    assert dossier.page_count == len(PdfReader(io.BytesIO(stored)).pages)
    assert dossier.ready_at is not None

    (entry,) = audited(store)
    assert entry.target_id == dossier_id
    assert entry.detail == {
        "sha256": dossier.sha256,
        "documents": 3,
        "page_count": dossier.page_count,
    }


@pytest.mark.req("REQ-013")
def test_the_pdf_holds_what_was_stored(worker, store, bucket, selected):
    dossier_id = ask(store, bucket, selected)

    worker(delivered(dossier_id))

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None
    stored = bucket.history[(keys.dossier_key(TENANT, dossier_id), dossier.s3_version_id or "")]
    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(stored)).pages)
    assert hashlib.sha256(PHOTO).hexdigest() in text
    assert "Device: Samsung SM-A536B" in text
    assert "Location: not recorded" in text
    assert "Mr Botha" in text
    assert "(RHA-5)" in text


# ------------------------------------------------------ trusting nothing ---
@pytest.mark.req("REQ-001", "REQ-013")
def test_the_job_objects_own_list_is_not_what_is_built(worker, store, bucket, selected):
    """The job object names another tenant's photo; the dossier doesn't. What is built is the
    dossier's list, read in the tenant's own partition (dossier.md §4)."""
    theirs = upload(store, bucket, DocumentKind.PHOTO, b"\xff\xd8 theirs", "image/jpeg", OTHER)
    dossier_id = ask(store, bucket, selected, listed=[*selected, theirs])

    worker(delivered(dossier_id))

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.READY
    stored = bucket.history[(keys.dossier_key(TENANT, dossier_id), dossier.s3_version_id or "")]
    assert hashlib.sha256(b"\xff\xd8 theirs").hexdigest().encode() not in stored
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(stored)).pages)
    assert theirs not in text


@pytest.mark.req("REQ-001", "REQ-013")
def test_a_dossier_naming_another_tenants_document_fails_with_the_reason(
    worker, store, bucket, selected
):
    theirs = upload(store, bucket, DocumentKind.PHOTO, b"\xff\xd8 theirs", "image/jpeg", OTHER)
    dossier_id = ask(store, bucket, [*selected, theirs])

    assert worker(delivered(dossier_id)) == {"batchItemFailures": []}

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason == selection.NOT_YOURS
    assert not [k for k in bucket.objects if k.startswith("dossiers/")]
    assert audited(store) == []


@pytest.mark.req("REQ-001")
def test_a_job_for_a_dossier_the_tenant_doesnt_have_is_done_with(worker, store, bucket):
    """A deleted account, most likely: nothing to build, nothing to mark, nothing to retry."""
    dossier_id = str(uuid.uuid4())
    job = {
        "version": 1,
        "dossier_id": dossier_id,
        "tenant_id": TENANT,
        "document_ids": [],
        "requested_at": "2026-10-01T09:00:00Z",
    }
    bucket.put(keys.dossier_job_key(dossier_id), json.dumps(job).encode())

    assert worker(delivered(dossier_id)) == {"batchItemFailures": []}
    assert not [k for k in bucket.objects if k.startswith("dossiers/")]


@pytest.mark.req("REQ-013")
def test_a_job_object_that_names_another_dossier_is_refused(worker, store, bucket, selected):
    dossier_id = ask(store, bucket, selected)
    key = keys.dossier_job_key(dossier_id)
    forged = json.loads(bucket.objects[key]) | {"dossier_id": str(uuid.uuid4())}
    bucket.put(key, json.dumps(forged).encode())

    answer = worker(delivered(dossier_id))

    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.REQUESTED


# --------------------------------------------------- deliveries and retries ---
@pytest.mark.req("REQ-013", "REQ-011")
def test_a_finished_dossier_is_left_alone_when_its_job_comes_again(worker, store, bucket, selected):
    dossier_id = ask(store, bucket, selected)
    worker(delivered(dossier_id))
    first = store.get_dossier(TENANT, dossier_id)

    assert worker(delivered(dossier_id, receives=2)) == {"batchItemFailures": []}

    assert store.get_dossier(TENANT, dossier_id) == first
    assert len(audited(store)) == 1


@pytest.mark.req("REQ-013")
def test_a_retry_after_a_failed_attempt_finishes_the_dossier(store, bucket, selected, monkeypatch):
    """dossier.md §4: stopping at `compiling` would leave the dossier there for good."""
    throttled = Throttled(failures=1)
    throttled.objects, throttled.versions = bucket.objects, bucket.versions
    throttled.modified, throttled.history = bucket.modified, bucket.history
    monkeypatch.setattr(handler, "store_for", lambda: store)
    monkeypatch.setattr(handler, "s3_for", lambda: throttled)
    store.create_tenant(TENANT, created_at="2026-09-01T08:00:00Z")
    dossier_id = ask(store, throttled, selected)

    failed = handler.handler(delivered(dossier_id, receives=1))
    halfway = store.get_dossier(TENANT, dossier_id)
    again = handler.handler(delivered(dossier_id, receives=2))

    assert failed == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert halfway is not None and halfway.status is DossierStatus.COMPILING
    assert again == {"batchItemFailures": []}
    done = store.get_dossier(TENANT, dossier_id)
    assert done is not None and done.status is DossierStatus.READY


@pytest.mark.req("REQ-013")
def test_the_third_failure_marks_the_dossier_failed_and_still_goes_to_the_dlq(
    store, bucket, selected, monkeypatch
):
    throttled = Throttled(failures=99)
    throttled.objects, throttled.versions = bucket.objects, bucket.versions
    throttled.modified, throttled.history = bucket.modified, bucket.history
    monkeypatch.setattr(handler, "store_for", lambda: store)
    monkeypatch.setattr(handler, "s3_for", lambda: throttled)
    store.create_tenant(TENANT, created_at="2026-09-01T08:00:00Z")
    dossier_id = ask(store, throttled, selected)

    answer = handler.handler(delivered(dossier_id, receives=3))

    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason == handler.NOT_BUILT


@pytest.mark.req("REQ-013", "REQ-011")
def test_two_builds_at_once_record_one_pdf_and_one_audit_entry(
    worker, store, bucket, selected, monkeypatch
):
    """The other delivery records its PDF while this one is still building. This one's `ready`
    is refused, so the dossier keeps describing the other's version, whose digest it holds, and
    this one writes no audit entry (dossier.md §4)."""
    dossier_id = ask(store, bucket, selected)
    real_build = pdf.build

    def racing(*args: Any, **kwargs: Any) -> pdf.Built:
        built = real_build(*args, **kwargs)
        store.finish_dossier(
            TENANT,
            dossier_id,
            s3_key=keys.dossier_key(TENANT, dossier_id),
            s3_version_id="the-other-one",
            sha256="0" * 64,
            page_count=1,
            size_bytes=1,
            ready_at="2026-10-01T09:00:30Z",
        )
        return built

    monkeypatch.setattr(pdf, "build", racing)

    assert worker(delivered(dossier_id)) == {"batchItemFailures": []}

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.READY
    assert dossier.s3_version_id == "the-other-one" and dossier.sha256 == "0" * 64
    assert audited(store) == []


# ------------------------------------------------------------ what it finds ---
@pytest.mark.req("REQ-013")
def test_a_file_whose_bytes_changed_is_still_in_the_dossier_and_marked(
    worker, store, bucket, selected
):
    photo = selected[1]
    bucket.put(keys.upload_key(TENANT, DocumentKind.PHOTO, photo), b"\xff\xd8 edited", "v1")
    dossier_id = ask(store, bucket, selected)

    worker(delivered(dossier_id))

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.READY
    stored = bucket.history[(keys.dossier_key(TENANT, dossier_id), dossier.s3_version_id or "")]
    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(stored)).pages)
    assert "does not match the digest recorded when it was stored" in text


@pytest.mark.req("REQ-013")
def test_a_dossier_that_would_pass_100_mb_fails_with_the_reason(
    worker, store, bucket, selected, monkeypatch
):
    monkeypatch.setattr(handler, "LIMIT_BYTES", 1000)
    dossier_id = ask(store, bucket, selected)

    assert worker(delivered(dossier_id)) == {"batchItemFailures": []}

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason == handler.TOO_MANY
    assert not [k for k in bucket.objects if k.startswith("dossiers/")]


@pytest.mark.req("REQ-013")
def test_more_chat_than_the_function_has_time_to_set_fails_with_the_reason(
    worker, store, bucket, selected, monkeypatch
):
    """A 5 MB export, the most one upload may be, is 43,000 messages and takes about 40 s to set
    on a laptop (T043's measurement); the function has 300 s on a slower CPU. So one dossier takes
    at most 5 MB of chat, refused before a byte is read."""
    monkeypatch.setattr(handler, "CHAT_LIMIT_BYTES", len(EXPORT) - 1)
    dossier_id = ask(store, bucket, selected)

    assert worker(delivered(dossier_id)) == {"batchItemFailures": []}

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason == handler.TOO_MUCH_CHAT


@pytest.mark.req("REQ-013")
def test_a_document_that_isnt_finished_any_more_fails_the_dossier(worker, store, bucket, selected):
    """Between the request and the build, a document can't become unfinished in this project,
    but the worker checks as if it could: the rule is the api's, in the same words."""
    store.set_document_status(TENANT, selected[1], DocumentStatus.FAILED, failure_reason="x")
    dossier_id = ask(store, bucket, selected)

    worker(delivered(dossier_id))

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason is not None and "couldn't be processed" in dossier.failure_reason


def test_the_health_check_touches_nothing():
    assert handler.handler({"realm": "health"}) == {"ok": True}
