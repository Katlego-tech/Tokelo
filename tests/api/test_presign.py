"""Pre-signed uploads (REQ-002, REQ-003, NFR-006; docs/design/api.md §4, §6).

The signing is local: no call leaves this test. What it checks is the policy the tenant's browser
is given — which key it may write, which content type, how big, and for how long — because that
policy is the whole of the permission S3 will honour."""

import base64
import json
from datetime import UTC, datetime

import pytest

from tokelo.api.handler import handler
from tokelo.core.model import DocumentStatus

TENANT = "11111111-1111-4111-8111-111111111111"
BUCKET = "tokelo-test-documents-000000000000"


@pytest.fixture
def api(store, monkeypatch):
    from tokelo.api import documents, uploads

    monkeypatch.setenv("TOKELO_DOCUMENTS_BUCKET", BUCKET)
    monkeypatch.setattr(documents, "store_for", lambda: store)
    monkeypatch.setattr(uploads, "store_for", lambda: store)
    return handler


def post(body: dict | None, tenant: str | None = TENANT) -> dict:
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": "/api/uploads",
        "requestContext": {"http": {"method": "POST", "path": "/api/uploads"}},
        "body": json.dumps(body) if body is not None else None,
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def a_lease(**changes) -> dict:
    return {
        "kind": "lease",
        "content_type": "application/pdf",
        "size_bytes": 5_000_000,
        "filename": "my-lease.pdf",
    } | changes


def policy_of(answer: dict) -> list:
    """The conditions S3 will hold the browser to, out of the signed policy document."""
    fields = json.loads(answer["body"])["fields"]
    return json.loads(base64.b64decode(fields["policy"]))["conditions"]


@pytest.mark.req("REQ-002")
def test_the_url_allows_one_key_one_type_and_a_maximum_size(api, store):
    answer = api(post(a_lease()))
    assert answer["statusCode"] == 201
    given = json.loads(answer["body"])

    document_id = given["document_id"]
    key = f"uploads/{TENANT}/lease/{document_id}"
    conditions = policy_of(answer)

    # The key is fixed, not a prefix: this URL writes that object and no other — not another
    # tenant's, and not a second file of this tenant's (REQ-002).
    assert {"key": key} in conditions
    assert {"Content-Type": "application/pdf"} in conditions
    assert ["content-length-range", 1, 20 * 1024 * 1024] in conditions
    assert given["fields"]["key"] == key
    assert given["url"].startswith("https://")


@pytest.mark.req("REQ-002")
def test_the_api_records_the_document_but_never_its_bytes(api, store):
    given = json.loads(api(post(a_lease()))["body"])

    stored = store.get_document(TENANT, given["document_id"])
    assert stored is not None
    assert stored.document.status is DocumentStatus.REQUESTED
    assert stored.document.s3_key == f"uploads/{TENANT}/lease/{given['document_id']}"
    assert stored.document.size_bytes == 5_000_000
    # Nothing is stored until S3 tells us it arrived: no digest, no version, no stored_at.
    assert stored.document.sha256 is None
    assert stored.document.s3_version_id is None
    assert stored.document.stored_at is None


@pytest.mark.req("NFR-006")
def test_the_url_expires_within_fifteen_minutes(api):
    given = json.loads(api(post(a_lease()))["body"])
    expires = datetime.strptime(given["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    ahead = (expires - datetime.now(UTC)).total_seconds()
    assert 0 < ahead <= 15 * 60


@pytest.mark.req("REQ-002")
def test_the_post_goes_to_the_host_the_page_may_reach_signed_with_sigv4(api):
    """The browser posts the file itself, with XMLHttpRequest, so the page's Content-Security-
    Policy decides whether it may. It allows the bucket's regional address and nothing else
    (static.py). Left to itself, botocore signs for the global `<bucket>.s3.amazonaws.com`, which
    the page refuses to post to, and it signs with Signature Version 2, which S3 has deprecated."""
    from tokelo.api import static

    given = json.loads(api(post(a_lease()))["body"])

    host = f"https://{BUCKET}.s3.eu-west-1.amazonaws.com"
    assert given["url"].rstrip("/") == host
    csp = static.content_security_policy(
        {"AWS_REGION": "eu-west-1", "TOKELO_DOCUMENTS_BUCKET": BUCKET}
    )
    (connect,) = [d for d in csp.split("; ") if d.startswith("connect-src ")]
    assert host in connect.split()
    assert given["fields"]["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    assert "AWSAccessKeyId" not in given["fields"]


@pytest.mark.req("REQ-003")
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"kind": "deed"}, "kind"),
        ({"content_type": "application/zip"}, "content type"),
        ({"size_bytes": 20 * 1024 * 1024 + 1}, "20 MB"),
        ({"size_bytes": 0}, "empty"),
        ({"kind": "chat", "content_type": "text/plain", "size_bytes": 6 * 1024 * 1024}, "5 MB"),
    ],
)
def test_a_file_this_project_cant_use_is_refused_with_the_reason(api, store, change, reason):
    answer = api(post(a_lease(**change)))
    assert answer["statusCode"] == 422
    body = json.loads(answer["body"])
    assert body["error"]["code"] == "refused"
    assert reason in body["error"]["message"]
    # Nothing was written, so a refused upload leaves no half-made record behind.
    assert store.list_documents(TENANT) == []


@pytest.mark.req("REQ-003")
@pytest.mark.parametrize(
    ("kind", "content_type"),
    [
        ("lease", "application/pdf"),
        ("lease", "image/jpeg"),
        ("lease", "image/png"),
        ("photo", "image/jpeg"),
        ("notice", "application/pdf"),
        ("chat", "text/plain"),
    ],
)
def test_every_kind_a_tenant_has_is_accepted(api, kind, content_type):
    answer = api(post(a_lease(kind=kind, content_type=content_type, size_bytes=1024)))
    assert answer["statusCode"] == 201
    assert {"Content-Type": content_type} in policy_of(answer)


@pytest.mark.req("REQ-002")
def test_a_request_that_makes_no_sense_is_refused_not_signed(api):
    for body in (None, {}, {"kind": "lease"}, {"kind": "lease", "content_type": "application/pdf"}):
        answer = api(post(body))
        assert answer["statusCode"] == 422, body
        assert json.loads(answer["body"])["error"]["code"] == "refused"


@pytest.mark.req("REQ-001")
def test_an_upload_url_is_never_issued_without_a_verified_claim(api):
    answer = api(post(a_lease(), tenant=None))
    assert answer["statusCode"] == 401


@pytest.mark.req("REQ-011")
def test_the_first_upload_request_makes_the_tenants_row(api, store):
    """api.md §4: the `api` makes the tenant's row on their first request. It holds the pseudonym
    their audit entries are filed under, and without it the workers have nowhere to file the
    upload (T059)."""
    assert store.get_tenant(TENANT) is None

    api(post(a_lease()))

    tenant = store.get_tenant(TENANT)
    assert tenant is not None
    assert tenant["audit_subject"]


@pytest.mark.req("REQ-011")
def test_the_pseudonym_never_changes_under_the_tenants_own_trail(api, store):
    api(post(a_lease()))
    first = store.get_tenant(TENANT)["audit_subject"]

    api(post(a_lease()))

    assert store.get_tenant(TENANT)["audit_subject"] == first


@pytest.mark.req("REQ-011")
def test_a_refused_request_writes_nothing(api, store):
    assert api(post(a_lease(kind="spreadsheet")))["statusCode"] == 422
    assert store.get_tenant(TENANT) is None


@pytest.mark.req("REQ-011")
def test_an_upload_through_the_api_is_audited_by_the_worker(api, store, monkeypatch):
    """The defect T059 fixes, end to end: a tenant asks for an upload, the file arrives, and the
    `evidence` worker files the upload in their audit log. Before T059 nothing made the tenant's
    row, so the worker found nobody to file it under and skipped it (REQ-011)."""
    from fakes import Bucket, batch, s3_record
    from tokelo.core.model import AuditAction
    from tokelo.evidence import handler as evidence

    bucket = Bucket()
    monkeypatch.setattr(evidence, "s3_for", lambda: bucket)
    monkeypatch.setattr(evidence, "store_for", lambda: store)

    photo = {"kind": "photo", "content_type": "image/jpeg", "size_bytes": 2_000}
    given = json.loads(api(post(photo))["body"])
    key = f"uploads/{TENANT}/photo/{given['document_id']}"
    bucket.put(key, b"\xff\xd8\xff\xe0" + b"x" * 1_996)

    evidence.handler(batch(s3_record(key)))

    subject = store.get_tenant(TENANT)["audit_subject"]
    uploads = [e for e in store.list_audit(subject) if e.action is AuditAction.UPLOAD]
    assert [e.target_id for e in uploads] == [given["document_id"]]
