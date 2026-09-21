"""Serving a lease's flags (REQ-001, REQ-004 to REQ-007; docs/design/api.md §6).

Everything the worker found is already in the database (T033, T057). What is held here is what
leaves the function: the shape api.md promises, the notice on every answer, and — above all —
that it only ever leaves for the tenant whose lease it is.

The three answers a tenant can get are all here: the flags, `409` while the lease is still being
read, and `404`, which is also what someone else's lease looks like (REQ-001).
"""

import json
import re

import pytest

from tokelo.api.handler import handler
from tokelo.core.model import (
    Clause,
    Document,
    DocumentKind,
    DocumentStatus,
    Lease,
    LeaseStatus,
    Page,
    PageSource,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "33333333-3333-4333-8333-333333333333"

NOTICE = "This is legal information, not legal advice."

# A verdict on a clause, or a direction to the tenant: either turns information into advice
# (REQ-007). The words alone are not the problem — "unlawful occupier" is the PIE Act's own term
# and a flag may quote it — so what is caught is the assertion. tests/unit/test_rules.py holds
# the fuller list, swept over every explanation in the catalogue.
VERDICT = re.compile(
    r"(is|are|was|were|would be|shall be|becomes?)\s+"
    r"(lawful|unlawful|illegal|void|invalid|unenforceable|valid|fine|allowed|permitted)\b"
    r"|legal advice|you (should|must|can claim)",
    re.I,
)

A_FLAG = {
    "rule_id": "eviction-without-court-order",
    "explanation": "A landlord may only evict a tenant under a court order.",
    "sections": [
        {
            "id": "PIE-4",
            "act": (
                "Prevention of Illegal Eviction from and Unlawful Occupation of Land Act 19 of 1998"
            ),
            "section": "4",
            "title": "Eviction of unlawful occupiers",
        }
    ],
    "catalogue_version": "2026-09-21.1",
}


@pytest.fixture
def api(store, monkeypatch):
    from tokelo.api import documents, leases

    monkeypatch.setattr(documents, "store_for", lambda: store)
    monkeypatch.setattr(leases, "store_for", lambda: store)
    return handler


def get(path: str, tenant: str | None = TENANT) -> dict:
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": path,
        "requestContext": {"http": {"method": "GET", "path": path}},
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def a_lease(
    tenant: str = TENANT,
    document_id: str = DOCUMENT,
    status: LeaseStatus = LeaseStatus.ANALYSED,
    kind: DocumentKind = DocumentKind.LEASE,
) -> Document:
    return Document(
        id=document_id,
        kind=kind,
        status=DocumentStatus.PROCESSED,
        s3_key=f"uploads/{tenant}/{kind}/{document_id}",
        content_type="application/pdf",
        size_bytes=120_000,
        requested_at="2026-09-21T08:00:00Z",
        lease=Lease(page_count=2, pages_done=2, status=status),
    )


@pytest.fixture
def analysed(store):
    """A lease that has been read and flagged: one flagged clause, one quiet one, one page that
    could not be read at all."""
    store.create_document(TENANT, a_lease())
    store.put_page(TENANT, DOCUMENT, Page(number=1, source=PageSource.TEXT_LAYER, text="one"))
    store.put_page(TENANT, DOCUMENT, Page(number=2, source=PageSource.OCR, text="", readable=False))
    store.put_clause(
        TENANT,
        DOCUMENT,
        Clause(
            ordinal=1,
            label="7.2",
            first_page=1,
            text="The landlord may evict the tenant without recourse to a court of law.",
            flags=[A_FLAG],
        ),
    )
    store.put_clause(
        TENANT,
        DOCUMENT,
        Clause(
            ordinal=2,
            label="8.2",
            first_page=1,
            text="The tenant shall keep the garden in a neat and tidy condition.",
        ),
    )
    return store


def body_of(answer: dict) -> dict:
    return json.loads(answer["body"])


@pytest.mark.req("REQ-005")
def test_a_lease_comes_back_as_its_clauses_in_order(api, analysed):
    answer = api(get(f"/api/leases/{DOCUMENT}/flags"))
    assert answer["statusCode"] == 200

    body = body_of(answer)
    assert body["status"] == "analysed"
    assert body["notice"] == NOTICE
    assert [c["label"] for c in body["clauses"]] == ["7.2", "8.2"]
    assert body["clauses"][0]["first_page"] == 1
    assert "court of law" in body["clauses"][0]["text"]


@pytest.mark.req("REQ-006")
def test_a_flag_carries_its_explanation_and_the_section_it_rests_on(api, analysed):
    """REQ-006: a tenant can look up what a flag stands on. The catalogue's version is kept in
    the database for later, but it is not part of what the API promises (api.md §6)."""
    flag = body_of(api(get(f"/api/leases/{DOCUMENT}/flags")))["clauses"][0]["flags"][0]

    assert set(flag) == {"rule_id", "explanation", "sections"}
    assert flag["explanation"]
    assert set(flag["sections"][0]) == {"id", "act", "section", "title"}
    assert flag["sections"][0]["id"] == "PIE-4"


@pytest.mark.req("REQ-007")
def test_a_clause_with_no_flag_says_what_was_checked_and_never_that_it_is_lawful(api, analysed):
    """A clause nothing matched carries the finding, and nothing in the clauses reaches a verdict.

    The notice is excluded from the sweep on purpose: "not legal advice" is the one place those
    words belong, and it is asserted above.
    """
    body = body_of(api(get(f"/api/leases/{DOCUMENT}/flags")))
    quiet = body["clauses"][1]

    assert quiet["flags"] == []
    assert quiet["finding"] == "no issue found by these checks"

    said = VERDICT.search(json.dumps(body["clauses"]))
    assert not said, f"a clause reads {said.group(0)!r}"


@pytest.mark.req("REQ-004")
def test_the_pages_that_could_not_be_read_are_named_by_number(api, analysed):
    """REQ-004. A tenant whose second page failed is told which page, so they can photograph
    that one again rather than the whole lease."""
    assert body_of(api(get(f"/api/leases/{DOCUMENT}/flags")))["unreadable_pages"] == [2]


@pytest.mark.req("REQ-005")
def test_a_lease_still_being_read_says_so_rather_than_showing_half_of_it(api, store):
    """api.md §6: 409. Half a lease's clauses would read as a lease with fewer problems than it
    has, which is the one wrong answer this endpoint could give."""
    store.create_document(TENANT, a_lease(status=LeaseStatus.READING))

    answer = api(get(f"/api/leases/{DOCUMENT}/flags"))
    assert answer["statusCode"] == 409
    assert body_of(answer)["error"]["code"] == "still_reading"


@pytest.mark.req("REQ-004")
def test_a_lease_nothing_could_be_read_from_comes_back_as_failed(api, store):
    """Not an error: the tenant asked a fair question and the answer is that the reading failed.
    The document's own record carries the reason (`GET /api/documents/{id}`)."""
    store.create_document(TENANT, a_lease(status=LeaseStatus.FAILED))

    answer = api(get(f"/api/leases/{DOCUMENT}/flags"))
    assert answer["statusCode"] == 200
    assert body_of(answer)["status"] == "failed"
    assert body_of(answer)["clauses"] == []


@pytest.mark.req("REQ-001")
def test_another_tenants_lease_is_not_found_rather_than_forbidden(api, analysed):
    """T034's Done, and REQ-001. A 403 would confirm the lease exists, which is the other
    tenant's business and nobody else's — so it is the same 404 as a lease that never was."""
    answer = api(get(f"/api/leases/{DOCUMENT}/flags", tenant=OTHER))
    assert answer["statusCode"] == 404
    assert body_of(answer)["error"]["code"] == "not_found"


@pytest.mark.req("REQ-001")
def test_a_document_that_is_not_a_lease_has_no_flags_to_serve(api, store):
    """A photograph of a leaking geyser is evidence, not a lease. Asking this endpoint for one
    is a 404, not an empty lease."""
    store.create_document(TENANT, a_lease(kind=DocumentKind.PHOTO))

    assert api(get(f"/api/leases/{DOCUMENT}/flags"))["statusCode"] == 404


@pytest.mark.req("REQ-001")
def test_a_lease_that_never_existed_is_a_404(api, store):
    assert api(get(f"/api/leases/{DOCUMENT}/flags"))["statusCode"] == 404


def test_the_route_is_only_the_one_in_the_contract(api, analysed):
    """api.md §6 has one leases route. Anything else under /api/leases/ is a 404, not a guess."""
    assert api(get(f"/api/leases/{DOCUMENT}"))["statusCode"] == 404
    assert api(get("/api/leases"))["statusCode"] == 404
