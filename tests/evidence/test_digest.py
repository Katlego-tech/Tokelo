"""Fingerprinting an evidence file as it is stored (REQ-008, REQ-011; evidence.md §4, §9).

A tenant's photograph is worth something at a Tribunal only if it can be shown to be the file
that was uploaded and not one edited since. That rests entirely on the digest being taken **from
the stored object**, by version, and never from anything a client says — which is what is held
here.

The database is real (DynamoDB Local): the digest is written under a condition that lets it be
written once and never changed, and that condition is the whole of REQ-008's promise.
"""

import hashlib
from datetime import UTC, datetime

import pytest

from fakes import STORED_AT, Bucket, batch, s3_record
from tokelo.core import keys
from tokelo.core.model import AuditAction, Document, DocumentKind, DocumentStatus
from tokelo.evidence import handler

TENANT = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
PHOTO_KEY = keys.upload_key(TENANT, DocumentKind.PHOTO, DOCUMENT)

# Not a real JPEG: T037 hashes bytes and reads no pixels. The photographs with and without EXIF
# arrive with T038, which is the task that has to look inside one.
PHOTO = b"\xff\xd8\xff\xe0" + b"a damp patch on the bedroom ceiling, 14B Marabastad Road" * 40


@pytest.fixture
def bucket(monkeypatch) -> Bucket:
    stub = Bucket()
    monkeypatch.setattr(handler, "s3_for", lambda: stub)
    return stub


@pytest.fixture
def worker(store, bucket, monkeypatch):
    monkeypatch.setattr(handler, "store_for", lambda: store)
    return handler.handler


@pytest.fixture
def uploaded(store, bucket):
    """A tenant who asked to upload a photo, and the object now in the bucket."""

    def upload(
        body: bytes = PHOTO,
        kind: DocumentKind = DocumentKind.PHOTO,
        content_type: str = "image/jpeg",
        declared: int | None = None,
    ) -> bytes:
        store.create_tenant(TENANT, created_at="2026-09-21T08:00:00Z")
        store.create_document(
            TENANT,
            Document(
                id=DOCUMENT,
                kind=kind,
                status=DocumentStatus.REQUESTED,
                s3_key=keys.upload_key(TENANT, kind, DOCUMENT),
                content_type=content_type,
                size_bytes=len(body) if declared is None else declared,
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        bucket.put(keys.upload_key(TENANT, kind, DOCUMENT), body)
        return body

    return upload


@pytest.mark.req("REQ-008")
def test_the_digest_is_the_stored_objects_own(worker, store, uploaded):
    """The whole of REQ-008. The digest has to be `sha256sum` of what is in the bucket, or
    nothing built on it means anything."""
    body = uploaded()

    assert worker(batch(s3_record(PHOTO_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.sha256 == hashlib.sha256(body).hexdigest()
    assert stored.document.s3_version_id == "v1"
    assert stored.document.status is DocumentStatus.PROCESSED


@pytest.mark.req("REQ-008")
def test_the_time_recorded_is_when_storage_took_the_file_not_when_the_worker_woke(
    worker, store, uploaded
):
    """`stored_at` is the object's own LastModified (evidence.md §4). A worker that stamped the
    moment it happened to run would date the evidence to whenever the queue got round to it —
    minutes later, or hours after a redrive."""
    uploaded()

    worker(batch(s3_record(PHOTO_KEY)))

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.stored_at == STORED_AT.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.req("REQ-008")
def test_nothing_the_client_said_about_the_file_is_believed(worker, store, uploaded, bucket):
    """ "Takes the digest from the stored object, not from the client" (T037's Done). The upload
    declared one size and stored something else; what is recorded describes the object."""
    body = uploaded(declared=7)

    worker(batch(s3_record(PHOTO_KEY, size=7)))

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.sha256 == hashlib.sha256(body).hexdigest()


@pytest.mark.req("REQ-008")
def test_a_second_delivery_changes_nothing(worker, store, uploaded):
    """ADR-0007, and REQ-008's "never changes". The digest is written under a condition, so the
    first one stands however many times the message arrives."""
    uploaded()

    worker(batch(s3_record(PHOTO_KEY)))
    once = store.get_document(TENANT, DOCUMENT)
    worker(batch(s3_record(PHOTO_KEY, message_id="m2", receives=2)))
    twice = store.get_document(TENANT, DOCUMENT)

    assert once is not None and twice is not None
    assert once.document.item() == twice.document.item()


@pytest.mark.req("REQ-011")
def test_the_upload_is_in_the_audit_log_once_under_the_tenants_pseudonym(worker, store, uploaded):
    """REQ-011. The entry belongs to the storing, which happens once, so a redelivery cannot add
    a second — and it is filed under the pseudonym, not the tenant's own ID."""
    uploaded()

    worker(batch(s3_record(PHOTO_KEY)))
    worker(batch(s3_record(PHOTO_KEY, message_id="m2")))

    tenant = store.get_tenant(TENANT)
    assert tenant is not None
    uploads = [
        e for e in store.list_audit(tenant["audit_subject"]) if e.action is AuditAction.UPLOAD
    ]
    assert len(uploads) == 1
    assert uploads[0].target_id == DOCUMENT
    assert uploads[0].detail["kind"] == "photo"


@pytest.mark.req("REQ-003")
def test_an_object_bigger_than_its_kind_allows_is_failed_with_the_reason(
    worker, store, uploaded, bucket
):
    """evidence.md §4's first failure path: a client that got around the POST policy. The size
    that counts is the object's real one, which only a HEAD can tell you."""
    uploaded(body=b"x" * 32, declared=32)
    bucket.put(PHOTO_KEY, b"y" * (21 * 1024 * 1024))

    assert worker(batch(s3_record(PHOTO_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.FAILED
    assert stored.document.failure_reason is not None
    assert "20 MB" in stored.document.failure_reason
    assert stored.document.sha256 is None, "nothing was fingerprinted"


@pytest.mark.req("REQ-016")
def test_an_object_that_is_gone_is_finished_with_quietly(worker, store, uploaded):
    """A deleted account takes its objects with it. There is nothing to hash and nothing to
    mark, so the message is done with rather than retried three times into the alarm."""
    uploaded()

    assert worker(batch(s3_record(PHOTO_KEY, version="v-gone"))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.REQUESTED


@pytest.mark.req("REQ-012")
@pytest.mark.parametrize("kind", [DocumentKind.NOTICE, DocumentKind.CHAT])
def test_a_notice_and_a_chat_export_are_fingerprinted_too(worker, store, uploaded, kind):
    """The evidence queue carries all three kinds (infra/modules/tokelo-env/events.tf). Their
    timeline entries are T041's; being fingerprinted is not."""
    body = uploaded(
        body=b"[2026/03/01, 18:04] Tenant: the geyser is leaking again\n" * 5,
        kind=kind,
        content_type="text/plain" if kind is DocumentKind.CHAT else "application/pdf",
    )

    worker(batch(s3_record(keys.upload_key(TENANT, kind, DOCUMENT))))

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.sha256 == hashlib.sha256(body).hexdigest()


@pytest.mark.req("REQ-017")
def test_a_lease_is_not_this_workers_business(worker, store):
    """A lease goes to the `ocr` worker. One arriving here could only be a misconfigured rule,
    so it is reported as a failure and drains to the dead-letter queue."""
    answer = worker(batch(s3_record(keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT))))
    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


def test_the_health_check_still_answers(worker):
    assert worker({"realm": "health"}) == {"ok": True}


@pytest.mark.req("REQ-008")
def test_a_big_file_is_hashed_without_being_held_whole(bucket):
    """A 20 MB photograph on a 512 MB function, several at a time. The digest is taken from the
    stream a chunk at a time, so what it costs doesn't grow with the file."""
    from tokelo.evidence import digest

    body = bytes(range(256)) * 8192  # 2 MB, and not compressible into a lucky coincidence
    bucket.put("uploads/x", body, modified=datetime(2026, 9, 21, 9, 0, tzinfo=UTC))

    taken = digest.of(bucket, "b", "uploads/x", "v1")
    assert taken.sha256 == hashlib.sha256(body).hexdigest()
    assert taken.size == len(body)
    assert taken.stored_at == "2026-09-21T09:00:00Z"
