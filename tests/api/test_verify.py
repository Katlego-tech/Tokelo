"""Verifying that an evidence file is unchanged (REQ-010, REQ-011; docs/design/api.md §6,
docs/design/evidence.md §4).

A digest recorded at upload is only worth something if it can be checked again later, by
something other than the tenant's word. What is held here is evidence.md's rule for that check:
the `api` reads the stored object **by the version the digest was taken of**, hashes it itself,
and compares — it never hashes anything a client sends, and a later write to the same key can't
stand in for the original.

S3 is the dictionary in tests/fakes.py, versioned as the bucket is; the store is DynamoDB Local.
"""

import hashlib
import json
import re

import pytest

from fakes import Bucket
from tokelo.core import keys
from tokelo.core.model import AuditAction, Document, DocumentKind, DocumentStatus

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
BUCKET = "tokelo-staging-documents"

PHOTO = b"\xff\xd8\xff\xe0" + b"the kitchen wall on the day we moved in" * 50
EDITED = b"\xff\xd8\xff\xe0" + b"the kitchen wall, with the damp painted out" * 50

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@pytest.fixture
def bucket() -> Bucket:
    return Bucket()


@pytest.fixture
def api(store, bucket, monkeypatch):
    from tokelo.api import evidence
    from tokelo.api.handler import handler

    monkeypatch.setenv("TOKELO_DOCUMENTS_BUCKET", BUCKET)
    monkeypatch.setattr(evidence, "store_for", lambda: store)
    monkeypatch.setattr(evidence, "s3_for", lambda: bucket)
    return handler


def verify(document_id: str = DOCUMENT, tenant: str | None = TENANT) -> dict:
    path = f"/api/evidence/{document_id}/verify"
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": path,
        "requestContext": {"http": {"method": "POST", "path": path}},
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def body_of(response: dict) -> dict:
    return json.loads(response["body"])


@pytest.fixture
def stored(store, bucket):
    """An evidence file as the `evidence` worker leaves it: in the bucket as version v1, with
    that version's digest recorded against it (T037)."""

    def make(
        kind: DocumentKind = DocumentKind.PHOTO,
        body: bytes = PHOTO,
        status: DocumentStatus = DocumentStatus.PROCESSED,
    ) -> str:
        key = keys.upload_key(TENANT, kind, DOCUMENT)
        store.create_document(
            TENANT,
            Document(
                id=DOCUMENT,
                kind=kind,
                status=DocumentStatus.REQUESTED,
                s3_key=key,
                content_type="image/jpeg",
                size_bytes=len(body),
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        bucket.put(key, body, version="v1")
        digest = hashlib.sha256(body).hexdigest()
        store.record_stored(TENANT, DOCUMENT, "v1", digest, "2026-09-21T08:30:00Z")
        if status is not DocumentStatus.STORED:
            store.set_document_status(TENANT, DOCUMENT, status)
        return digest

    return make


@pytest.mark.req("REQ-010")
def test_an_unchanged_file_matches(api, stored):
    recorded = stored()

    response = api(verify())

    assert response["statusCode"] == 200
    answer = body_of(response)
    assert answer["matches"] is True
    assert answer["recorded_sha256"] == recorded
    assert answer["computed_sha256"] == recorded
    assert STAMP.match(answer["verified_at"])
    assert set(answer) == {"matches", "recorded_sha256", "computed_sha256", "verified_at"}


@pytest.mark.req("REQ-010")
def test_a_file_whose_bytes_differ_from_its_digest_does_not_match(api, stored, bucket):
    """The stored bytes of the recorded version no longer hash to what was recorded. The answer
    says so, and shows both digests, so the tenant can see what differs."""
    recorded = stored()
    bucket.put(keys.upload_key(TENANT, DocumentKind.PHOTO, DOCUMENT), EDITED, version="v1")

    answer = body_of(api(verify()))

    assert answer["matches"] is False
    assert answer["recorded_sha256"] == recorded
    assert answer["computed_sha256"] == hashlib.sha256(EDITED).hexdigest()


@pytest.mark.req("REQ-010")
def test_a_later_version_of_the_object_cant_pass_as_the_original(api, stored, bucket):
    """evidence.md's threat table: an edited photo uploaded over the original is a new version,
    and verification reads the version the digest was taken of — not whatever is there now. The
    edit is never what gets hashed."""
    recorded = stored()
    bucket.put(keys.upload_key(TENANT, DocumentKind.PHOTO, DOCUMENT), EDITED, version="v2")

    answer = body_of(api(verify()))

    assert answer["computed_sha256"] == recorded
    assert answer["computed_sha256"] != hashlib.sha256(EDITED).hexdigest()
    assert answer["matches"] is True


@pytest.mark.req("REQ-010")
@pytest.mark.parametrize("kind", [DocumentKind.PHOTO, DocumentKind.NOTICE, DocumentKind.CHAT])
def test_every_kind_of_evidence_can_be_verified(api, stored, kind):
    stored(kind=kind)

    assert body_of(api(verify()))["matches"] is True


@pytest.mark.req("REQ-011")
def test_each_verification_is_an_audit_entry(api, stored, store):
    """REQ-011: every verification, filed under the tenant's pseudonym — so a tenant can't deny
    having verified a file, and the entry names nobody once the account is gone."""
    recorded = stored()

    first = body_of(api(verify()))
    api(verify())

    subject = store.get_tenant(TENANT)["audit_subject"]
    entries = [e for e in store.list_audit(subject) if e.action is AuditAction.VERIFY]
    assert len(entries) == 2
    assert all(e.target_id == DOCUMENT for e in entries)
    assert entries[0].detail == {
        "matches": True,
        "recorded_sha256": recorded,
        "computed_sha256": recorded,
    }
    assert first["verified_at"] in {e.at for e in entries}


@pytest.mark.req("REQ-001")
def test_someone_elses_file_is_a_404(api, stored, store):
    """The same answer as a file that doesn't exist, and nothing is read or audited for it."""
    stored()

    response = api(verify(tenant=OTHER))

    assert response["statusCode"] == 404
    assert store.get_tenant(OTHER) is None


@pytest.mark.req("REQ-010")
def test_a_file_that_was_never_uploaded_is_a_404(api):
    assert api(verify())["statusCode"] == 404


@pytest.mark.req("REQ-010")
def test_a_lease_is_not_evidence(api, stored):
    """REQ-010 is about evidence files. A lease is read and checked, not kept as evidence, and
    this endpoint answers for it as for anything else it doesn't hold."""
    stored(kind=DocumentKind.LEASE)

    assert api(verify())["statusCode"] == 404


@pytest.mark.req("REQ-010")
def test_a_file_not_stored_yet_is_a_409(api, store):
    """Asked for, but not uploaded or not fingerprinted yet: there is no digest to check against."""
    store.create_document(
        TENANT,
        Document(
            id=DOCUMENT,
            kind=DocumentKind.PHOTO,
            status=DocumentStatus.REQUESTED,
            s3_key=keys.upload_key(TENANT, DocumentKind.PHOTO, DOCUMENT),
            content_type="image/jpeg",
            size_bytes=10,
            requested_at="2026-09-21T08:00:00Z",
        ),
    )

    response = api(verify())

    assert response["statusCode"] == 409
    assert body_of(response)["error"]["code"] == "not_stored"


@pytest.mark.req("REQ-010")
def test_a_recorded_version_that_is_gone_is_a_404_not_a_match(api, stored, bucket):
    """The version the digest belongs to can't be read (the account is being deleted, REQ-016).
    There is nothing to compare, and "matches" must never be said of nothing."""
    stored()
    bucket.history.clear()
    bucket.objects.clear()

    response = api(verify())

    assert response["statusCode"] == 404
    assert "matches" not in body_of(response)


@pytest.mark.req("REQ-001")
def test_a_request_without_a_verified_tenant_is_refused(api, stored):
    assert api(verify(tenant=None))["statusCode"] == 401


def test_only_post_verifies(api, stored):
    event = verify()
    event["requestContext"]["http"]["method"] = "GET"

    assert api(event)["statusCode"] == 404
