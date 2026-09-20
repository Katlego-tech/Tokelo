"""The store: the keys, the queries and the conditional writes (docs/design/domain-model.md §3,
§6, §9). Against DynamoDB Local, so the conditions are the engine's, not a stand-in's."""

import pytest

from tokelo.core import model
from tokelo.core.model import (
    AuditAction,
    Document,
    DocumentKind,
    DocumentStatus,
    Dossier,
    DossierStatus,
    LeaseStatus,
    Page,
    PageSource,
    TimelineEntry,
    TimelineSource,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
DIGEST = "a" * 64


def a_document(document_id: str = DOCUMENT, kind: DocumentKind = DocumentKind.LEASE) -> Document:
    return Document(
        id=document_id,
        kind=kind,
        status=DocumentStatus.REQUESTED,
        s3_key=f"uploads/{TENANT}/{kind}/{document_id}",
        content_type="application/pdf",
        size_bytes=1024,
        requested_at="2026-09-20T06:00:00Z",
    )


@pytest.mark.req("REQ-008")
def test_a_digest_is_written_once_and_never_changes(store):
    store.create_document(TENANT, a_document())
    assert store.record_stored(TENANT, DOCUMENT, "v1", DIGEST, "2026-09-20T06:01:00Z") is True

    # The same job again, and a job that would rewrite history: both refused, and the first
    # digest stands. That is what makes the digest evidence (REQ-008).
    assert store.record_stored(TENANT, DOCUMENT, "v1", DIGEST, "2026-09-20T06:02:00Z") is False
    assert store.record_stored(TENANT, DOCUMENT, "v2", "b" * 64, "2026-09-20T06:03:00Z") is False

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.sha256 == DIGEST
    assert stored.document.s3_version_id == "v1"
    assert stored.document.status is DocumentStatus.STORED


@pytest.mark.req("REQ-017")
def test_the_same_document_created_twice_leaves_one_item(store):
    assert store.create_document(TENANT, a_document()) is True
    assert store.create_document(TENANT, a_document()) is False  # a redelivered job: a no-op
    assert len(store.list_documents(TENANT)) == 1


@pytest.mark.req("REQ-001")
def test_one_tenants_query_returns_nothing_of_anothers(store):
    store.create_document(TENANT, a_document())
    store.put_page(TENANT, DOCUMENT, Page(number=1, source=PageSource.TEXT_LAYER, text="mine"))

    # The same document ID, asked for by someone else: not 403, not another tenant's row — nothing.
    assert store.get_document(OTHER, DOCUMENT) is None
    assert store.list_documents(OTHER) == []

    store.create_document(OTHER, a_document(document_id="44444444-4444-4444-8444-444444444444"))
    assert [d.id for d in store.list_documents(TENANT)] == [DOCUMENT]


@pytest.mark.req("REQ-011")
def test_the_audit_log_outlives_the_tenant_it_stopped_naming(store):
    subject = store.create_tenant(TENANT, created_at="2026-09-20T05:00:00Z")
    store.append_audit(subject, AuditAction.UPLOAD, DOCUMENT, {"kind": "lease"})
    store.create_document(TENANT, a_document())
    store.put_page(TENANT, DOCUMENT, Page(number=1, source=PageSource.OCR, text="a page"))
    store.add_timeline_entry(
        TENANT,
        TimelineEntry(
            id="55555555-5555-4555-8555-555555555555",
            occurred_at="2026-09-19T12:00:00Z",
            source=TimelineSource.CAPTURE,
            summary="a photo was taken",
            document_id=DOCUMENT,
        ),
    )

    deleted = store.delete_tenant(TENANT)

    assert deleted >= 4  # the tenant, the document, its page, the timeline entry
    assert store.list_documents(TENANT) == []
    assert store.get_tenant(TENANT) is None
    assert store.get_document(TENANT, DOCUMENT) is None
    # The entries are still there, and nothing left can say whose they were (REQ-011, REQ-016).
    entries = store.list_audit(subject)
    assert [e.action for e in entries] == [AuditAction.UPLOAD]
    assert TENANT not in repr(entries)


@pytest.mark.req("REQ-011")
def test_an_audit_entry_is_never_overwritten(store):
    subject = store.create_tenant(TENANT, created_at="2026-09-20T05:00:00Z")
    first = store.append_audit(subject, AuditAction.VERIFY, DOCUMENT, {"matches": True})
    second = store.append_audit(subject, AuditAction.VERIFY, DOCUMENT, {"matches": False})
    assert first != second  # each entry has its own sort key, so neither can land on the other
    assert len(store.list_audit(subject)) == 2


@pytest.mark.req("REQ-004")
def test_a_lease_comes_back_with_its_pages_and_clauses_in_one_query(store):
    store.create_document(TENANT, a_document())
    store.put_page(TENANT, DOCUMENT, Page(number=2, source=PageSource.OCR, text="", readable=False))
    store.put_page(TENANT, DOCUMENT, Page(number=1, source=PageSource.TEXT_LAYER, text="page one"))
    store.put_clause(
        TENANT,
        DOCUMENT,
        model.Clause(
            ordinal=1,
            label="7.2",
            first_page=1,
            text="The landlord may enter at any time.",
            flags=[
                {
                    "rule_id": "entry-without-notice",
                    "catalogue_version": "2026-09-20",
                    "explanation": "The landlord must give reasonable notice.",
                    "section_ids": ["RHA-4-2"],
                }
            ],
        ),
    )
    store.set_lease(TENANT, DOCUMENT, page_count=2, pages_done=2, status=LeaseStatus.ANALYSED)

    lease = store.get_document(TENANT, DOCUMENT)
    assert lease is not None
    assert [p.number for p in lease.pages] == [1, 2]  # the sort key orders them, not the writes
    assert [p.readable for p in lease.pages] == [True, False]
    assert [c.label for c in lease.clauses] == ["7.2"]
    assert lease.clauses[0].flags[0]["section_ids"] == ["RHA-4-2"]
    assert lease.document.lease is not None
    assert lease.document.lease.status is LeaseStatus.ANALYSED


@pytest.mark.req("REQ-012")
def test_the_timeline_comes_back_in_time_order(store):
    for n, when in enumerate(
        ["2026-09-19T12:00:00Z", "2026-09-17T08:30:00Z", "2026-09-18T20:00:00Z"]
    ):
        store.add_timeline_entry(
            TENANT,
            TimelineEntry(
                id=f"6666666{n}-6666-4666-8666-666666666666",
                occurred_at=when,
                source=TimelineSource.NOTICE,
                summary=f"entry {n}",
                document_id=DOCUMENT,
            ),
        )
    assert [e.occurred_at for e in store.list_timeline(TENANT)] == [
        "2026-09-17T08:30:00Z",
        "2026-09-18T20:00:00Z",
        "2026-09-19T12:00:00Z",
    ]


@pytest.mark.req("REQ-013")
def test_a_dossier_keeps_the_documents_it_names(store):
    dossier_id = "77777777-7777-4777-8777-777777777777"
    store.create_dossier(
        TENANT,
        Dossier(
            id=dossier_id,
            status=DossierStatus.REQUESTED,
            document_ids=[DOCUMENT],
            requested_at="2026-09-20T07:00:00Z",
        ),
    )
    store.finish_dossier(
        TENANT,
        dossier_id,
        s3_key=f"dossiers/{TENANT}/{dossier_id}.pdf",
        sha256=DIGEST,
        ready_at="2026-09-20T07:05:00Z",
    )
    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None
    assert dossier.status is DossierStatus.READY
    assert dossier.document_ids == [DOCUMENT]
    assert dossier.sha256 == DIGEST
    assert store.get_dossier(OTHER, dossier_id) is None
