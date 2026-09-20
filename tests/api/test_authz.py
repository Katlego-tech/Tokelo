"""A tenant sees their own records and nothing else (REQ-001; docs/design/api.md §4, §6).

Against the real store, because the point of this task is that isolation is the partition key's
doing and not a filter somebody has to remember to write."""

import json

import pytest

from tokelo.api.handler import handler
from tokelo.core.model import Document, DocumentKind, DocumentStatus

MINE = "11111111-1111-4111-8111-111111111111"
THEIRS = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def api(store, monkeypatch):
    """The handler, with the store the fixture made."""
    from tokelo.api import documents

    monkeypatch.setattr(documents, "store_for", lambda: store)
    return handler


def request(path: str, tenant: str | None, method: str = "GET") -> dict:
    """An API Gateway HTTP API event (payload 2.0), as the JWT authorizer leaves it."""
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def a_document(tenant: str, document_id: str = DOCUMENT) -> Document:
    return Document(
        id=document_id,
        kind=DocumentKind.LEASE,
        status=DocumentStatus.STORED,
        s3_key=f"uploads/{tenant}/lease/{document_id}",
        content_type="application/pdf",
        size_bytes=2048,
        requested_at="2026-09-20T06:00:00Z",
        stored_at="2026-09-20T06:01:00Z",
        sha256="a" * 64,
        s3_version_id="v1",
    )


@pytest.mark.req("REQ-001")
def test_a_tenant_reads_their_own_document(api, store):
    store.create_document(MINE, a_document(MINE))
    answer = api(request(f"/api/documents/{DOCUMENT}", MINE))
    assert answer["statusCode"] == 200
    view = json.loads(answer["body"])
    assert view["id"] == DOCUMENT
    assert view["sha256"] == "a" * 64
    assert view["kind"] == "lease"


@pytest.mark.req("REQ-001")
def test_another_tenants_document_is_404_not_403(api, store):
    store.create_document(MINE, a_document(MINE))

    asked_for_theirs = api(request(f"/api/documents/{DOCUMENT}", THEIRS))
    never_existed = api(request("/api/documents/99999999-9999-4999-8999-999999999999", THEIRS))

    # Identical answers: a 403 would confirm the document exists, which is a tenant's business
    # and nobody else's (api.md §Threats).
    assert asked_for_theirs["statusCode"] == 404
    assert asked_for_theirs["body"] == never_existed["body"]
    assert "a" * 64 not in asked_for_theirs["body"]


@pytest.mark.req("REQ-001")
def test_the_list_holds_only_the_tenants_own(api, store):
    store.create_document(MINE, a_document(MINE))
    store.create_document(THEIRS, a_document(THEIRS, "44444444-4444-4444-8444-444444444444"))

    mine = json.loads(api(request("/api/documents", MINE))["body"])["documents"]
    theirs = json.loads(api(request("/api/documents", THEIRS))["body"])["documents"]

    assert [d["id"] for d in mine] == [DOCUMENT]
    assert [d["id"] for d in theirs] == ["44444444-4444-4444-8444-444444444444"]


@pytest.mark.req("REQ-001")
def test_a_request_without_a_verified_claim_is_refused(api, store):
    """API Gateway refuses these before the function sees them (infrastructure.md §6). The
    function refuses them too: an API that trusts its front door without checking is one
    configuration mistake away from serving everyone's records."""
    answer = api(request(f"/api/documents/{DOCUMENT}", None))
    assert answer["statusCode"] == 401
    assert json.loads(answer["body"])["error"]["code"] == "unauthenticated"


@pytest.mark.req("REQ-001")
def test_an_unknown_api_route_is_a_json_404(api):
    answer = api(request("/api/nothing-here", MINE))
    assert answer["statusCode"] == 404
    assert json.loads(answer["body"])["error"]["code"] == "not_found"
