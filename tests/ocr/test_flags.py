"""Flagging a lease's clauses (REQ-005, REQ-007; docs/design/ocr.md §4 "Analysis", §9).

This is where the four pieces of the lane meet: the pages the reader gave back (T029), the split
into clauses (T031), the catalogue of rules (T032), and the store. What comes out is what a
tenant is shown — so two things are held here above all.

**Every clause comes back, flagged or not.** A tenant reads their own lease, not a list of its
worst lines; a clause with nothing against it has to be there, and has to say so.

**Nothing is ever called lawful** (REQ-007). A clause no rule matched says the checks found no
issue — which is a statement about the checks, not about the clause. Tokelo has ten rules and
the law has rather more, and the difference between those two sentences is the difference
between legal information and legal advice.
"""

from pathlib import Path

import pytest

from tokelo.core.model import Document, DocumentKind, DocumentStatus, Lease, LeaseStatus
from tokelo.ocr import flags

LEASES = Path(__file__).resolve().parents[1] / "fixtures" / "leases"
PAGE_BREAK = "--- page 2 ---"

TENANT = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "33333333-3333-4333-8333-333333333333"

# The ten terms planted in the sample lease (T028), and the rules that should find them.
PLANTED = {
    "deposit-no-interest",
    "deposit-refund-delayed",
    "joint-inspection-waived",
    "lock-out-or-seizure",
    "eviction-without-court-order",
    "fixed-term-no-cancellation",
    "waiver-of-rights",
    "late-payment-penalty",
    "entry-without-notice",
    "no-receipt-for-payment",
}


@pytest.fixture
def lease() -> list[str]:
    return [page.strip() for page in (LEASES / "lease.txt").read_text().split(PAGE_BREAK)]


@pytest.fixture
def a_lease_document(store):
    """A lease that has been read: its pages are in, and it is waiting to be analysed."""
    store.create_document(
        TENANT,
        Document(
            id=DOCUMENT,
            kind=DocumentKind.LEASE,
            status=DocumentStatus.STORED,
            s3_key=f"uploads/{TENANT}/lease/{DOCUMENT}",
            content_type="application/pdf",
            size_bytes=120_000,
            requested_at="2026-09-21T08:00:00Z",
            lease=Lease(page_count=2, pages_done=2, status=LeaseStatus.READING),
        ),
    )
    return store


@pytest.mark.req("REQ-005")
def test_every_planted_term_in_the_sample_lease_is_found(lease):
    """T028 wrote ten terms into the sample lease that a South African tenant really meets. All
    ten have to come back attached to the clause they were written into."""
    found = {flag["rule_id"] for clause in flags.analyse(lease) for flag in clause.flags}
    assert PLANTED <= found, f"not found: {sorted(PLANTED - found)}"


@pytest.mark.req("REQ-005")
def test_a_flag_arrives_on_the_clause_it_belongs_to(lease):
    """A flag is shown against a clause, so it has to be on the right one: the deposit rule on
    the deposit clause, and the eviction rule on the eviction clause two pages later."""
    by_label = {clause.label: clause for clause in flags.analyse(lease)}

    assert "deposit-no-interest" in {f["rule_id"] for f in by_label["4.2"].flags}
    assert "eviction-without-court-order" in {f["rule_id"] for f in by_label["7.2"].flags}
    assert by_label["7.2"].first_page == 2


@pytest.mark.req("REQ-006")
def test_a_flag_carries_what_the_tenant_reads_and_the_law_it_rests_on(lease):
    """Every flag has to stand on a curated section: the explanation is the sentence a tenant
    reads, and the sections are what they can look up (REQ-006)."""
    by_label = {clause.label: clause for clause in flags.analyse(lease)}
    flag = next(f for f in by_label["4.2"].flags if f["rule_id"] == "deposit-no-interest")

    assert flag["explanation"].strip()
    assert flag["sections"], "a flag with no section is an opinion"
    for section in flag["sections"]:
        assert {"id", "act", "section", "title"} <= set(section)


@pytest.mark.req("REQ-007")
def test_a_clause_nothing_matched_says_the_checks_found_no_issue(lease):
    """The whole of REQ-007 in one assertion. "8.2 The tenant shall keep the garden in a neat and
    tidy condition" is an ordinary clause: nothing here has an opinion on it, and saying so is
    not the same as saying it is lawful."""
    by_label = {clause.label: clause for clause in flags.analyse(lease)}
    garden = by_label["8.2"]

    assert garden.flags == []
    assert flags.finding(garden) == "no issue found by these checks"
    assert flags.finding(by_label["4.2"]) is None, "a flagged clause has its flags, not a finding"


@pytest.mark.req("REQ-007")
def test_nothing_this_module_can_say_calls_a_clause_lawful(lease):
    """Not a rule's wording — test_rules.py holds that — but this module's own. A verdict must
    not be able to reach a tenant through the finding, whatever the rules say."""
    said = flags.NO_ISSUE.lower()
    for verdict in ("lawful", "legal", "valid", "enforceable", "you should", "you must"):
        assert verdict not in said


@pytest.mark.req("REQ-005")
def test_the_whole_lease_comes_back_and_not_only_its_worst_lines(lease):
    """A tenant reads their lease. Every clause the splitter found is returned, in order, with
    or without flags — and most of this lease is unflagged."""
    analysed = flags.analyse(lease)

    assert [clause.ordinal for clause in analysed] == sorted(c.ordinal for c in analysed)
    assert len(analysed) >= 20, "the sample lease has twenty clauses (T031)"
    assert any(clause.flags for clause in analysed)
    assert any(not clause.flags for clause in analysed)


@pytest.mark.req("REQ-004")
def test_a_page_that_could_not_be_read_is_a_hole_and_not_a_shift(lease):
    """An unreadable page is left out (REQ-004) and the pages after it keep their numbers, so a
    flag doesn't point a tenant at the wrong page of their own lease."""
    analysed = {c.label: c for c in flags.analyse([lease[0], "", lease[1]])}
    assert analysed["7.2"].first_page == 3


@pytest.mark.req("REQ-005")
def test_the_catalogue_version_is_kept_on_every_flag(lease):
    """The rules will improve. What a tenant was shown, and took to the Tribunal, has to stay
    readable afterwards — so each flag records the catalogue it came from (ocr.md §3)."""
    from tokelo.ocr import rules

    version = rules.catalogue().version
    assert version
    for clause in flags.analyse(lease):
        for flag in clause.flags:
            assert flag["catalogue_version"] == version


@pytest.mark.req("REQ-005")
def test_the_flags_are_stored_against_the_lease(a_lease_document, lease):
    """T033's Done. The clauses and their flags are written under the document, the lease becomes
    analysed, and the document is processed — which is what the API serves (T034)."""
    store = a_lease_document
    flags.record(store, TENANT, DOCUMENT, flags.analyse(lease))

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert len(stored.clauses) >= 20
    assert stored.document.status is DocumentStatus.PROCESSED
    assert stored.document.lease is not None
    assert stored.document.lease.status is LeaseStatus.ANALYSED
    assert stored.document.lease.page_count == 2, "the counts are not touched by the analysis"

    deposit = next(c for c in stored.clauses if c.label == "4.2")
    assert "deposit-no-interest" in {f["rule_id"] for f in deposit.flags}


@pytest.mark.req("REQ-005")
def test_a_job_delivered_twice_changes_nothing(a_lease_document, lease):
    """ADR-0007. SQS delivers at least once, so the analysis may run twice on the same lease.
    The second run must leave the tenant looking at exactly what the first one did — not at
    every clause twice, or at doubled flags."""
    store = a_lease_document
    analysed = flags.analyse(lease)

    flags.record(store, TENANT, DOCUMENT, analysed)
    once = store.get_document(TENANT, DOCUMENT)
    flags.record(store, TENANT, DOCUMENT, analysed)
    twice = store.get_document(TENANT, DOCUMENT)

    assert once is not None and twice is not None
    assert [c.item() for c in once.clauses] == [c.item() for c in twice.clauses]
    assert once.document.item() == twice.document.item()
