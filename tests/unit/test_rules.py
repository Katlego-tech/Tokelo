"""The rule catalogue (REQ-005, REQ-006, REQ-007; docs/design/ocr.md §3, §6).

A rule is the only thing that turns a clause in someone's lease into a flag on their screen, so
the tests here are about the catalogue as a body of work: that every rule catches what it says it
catches, misses what it says it misses, cites law this project actually holds, and explains
itself in words a tenant can read without ever telling them a clause is fine."""

import re

import pytest

from tokelo.core import sources
from tokelo.ocr import rules

# A verdict on the clause, or a direction to the tenant: either turns information into advice
# (REQ-007). The words themselves are not the problem — "unlawful occupier" is the PIE Act's own
# term, and a rule may quote it — so what is caught here is the assertion.
NEVER = re.compile(
    r"((is|are|was|were|would be|shall be|becomes?)\s+"
    r"(lawful|unlawful|illegal|void|invalid|unenforceable|valid|fine|allowed|permitted)\b"
    r"|legal advice|you (should|must|can claim)|we advise|entitled to (sue|damages))",
    re.I,
)


@pytest.mark.req("REQ-005")
def test_every_rule_catches_its_example_and_leaves_its_counter_example_alone():
    """A rule that can't catch its own example is broken; one that catches its counter-example
    would flag a clause that says the opposite of what the rule is about."""
    for rule in rules.catalogue().rules:
        assert rule.matches(rule.example), f"{rule.id}: its own example doesn't match"
        assert not rule.matches(rule.counter_example), (
            f"{rule.id}: its counter-example matches, so the rule is too broad"
        )


@pytest.mark.req("REQ-006")
def test_every_rule_cites_law_this_project_holds():
    curated = sources.ids()
    for rule in rules.catalogue().rules:
        assert rule.section_ids, f"{rule.id}: cites nothing"
        for section_id in rule.section_ids:
            assert section_id in curated, f"{rule.id} cites {section_id}, which isn't curated"


@pytest.mark.req("REQ-006")
def test_a_rule_that_cites_law_nobody_curated_is_refused_when_the_catalogue_loads():
    """Not caught later by a test, but refused at load: a catalogue that cites nothing real must
    not be able to run at all."""
    with pytest.raises(rules.BadCatalogue) as refused:
        rules.load(
            {
                "catalogue_version": "2026-09-21.1",
                "rule": [
                    {
                        "id": "MADE-UP",
                        "section_ids": ["RHA-999"],
                        "any_of": ["anything"],
                        "explanation": "…",
                        "example": "anything",
                        "counter_example": "nothing",
                    }
                ],
            },
            where="a test",
        )
    assert "RHA-999" in str(refused.value)


@pytest.mark.req("REQ-007")
def test_no_explanation_tells_a_tenant_a_clause_is_lawful_or_what_to_do():
    """Tokelo gives legal information. An explanation says what the law requires and leaves the
    conclusion to the tenant and, if it comes to it, the Tribunal."""
    for rule in rules.catalogue().rules:
        offending = NEVER.search(rule.explanation)
        assert not offending, f"{rule.id}: explanation says {offending.group(0)!r}"


@pytest.mark.req("REQ-005")
def test_an_explanation_is_written_for_the_person_reading_it():
    for rule in rules.catalogue().rules:
        assert len(rule.explanation) > 60, f"{rule.id}: too short to explain anything"
        assert len(rule.explanation) < 420, f"{rule.id}: too long for a phone screen"
        assert rule.explanation[0].isupper() and rule.explanation.rstrip().endswith("."), (
            f"{rule.id}: an explanation is sentences, not a fragment"
        )


@pytest.mark.req("REQ-005")
def test_the_catalogue_has_one_version_and_rules_have_their_own_ids():
    catalogue = rules.catalogue()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", catalogue.version), catalogue.version
    ids = [rule.id for rule in catalogue.rules]
    assert len(ids) == len(set(ids)), "two rules share an ID"


@pytest.mark.req("REQ-005")
def test_the_catalogue_covers_what_the_task_promised():
    """T032's Done: joint inspections, the deposit's interest and refund, unlawful dispossession,
    fixed-term cancellation, unfair terms and waivers, and eviction only by court order."""
    covered = {rule.id for rule in rules.catalogue().rules}
    for expected in (
        "joint-inspection-waived",
        "deposit-no-interest",
        "deposit-refund-delayed",
        "lock-out-or-seizure",
        "fixed-term-no-cancellation",
        "waiver-of-rights",
        "eviction-without-court-order",
    ):
        assert expected in covered, f"no rule for {expected}"


@pytest.mark.req("REQ-005")
@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        (
            "The deposit shall not bear interest and no interest shall be payable to the tenant.",
            "deposit-no-interest",
        ),
        (
            "The landlord may change the locks and remove the tenant's belongings if rent is late.",
            "lock-out-or-seizure",
        ),
        (
            "The tenant waives all rights under the Rental Housing Act and any other law.",
            "waiver-of-rights",
        ),
        (
            "The tenant may not cancel this lease before the end of the fixed period.",
            "fixed-term-no-cancellation",
        ),
        (
            "No incoming or outgoing inspection shall be required or conducted.",
            "joint-inspection-waived",
        ),
        (
            "The landlord may evict the tenant without recourse to a court of law.",
            "eviction-without-court-order",
        ),
    ],
)
def test_clauses_a_tenant_really_signs(clause, expected):
    """The wording here is the kind that turns up in lease templates sold to landlords."""
    flagged = {rule.id for rule in rules.catalogue().rules if rule.matches(clause)}
    assert expected in flagged, f"{clause!r} was not flagged by {expected}; flagged {flagged}"


@pytest.mark.req("REQ-007")
def test_an_ordinary_clause_is_left_alone():
    """The commonest failure of a checker like this is flagging everything. These are clauses a
    fair lease contains, and none of them is any rule's business."""
    for ordinary in (
        "The monthly rental is R6 500, payable in advance on the first day of each month.",
        "The tenant shall keep the garden in a neat and tidy condition.",
        "The lease begins on 1 March 2026 and endures for twelve months.",
        "The landlord shall refund the deposit together with interest within seven days of the "
        "joint outgoing inspection.",
        "The tenant may cancel this lease on twenty business days' written notice.",
    ):
        flagged = {rule.id for rule in rules.catalogue().rules if rule.matches(ordinary)}
        assert not flagged, f"{ordinary!r} was flagged by {flagged}"
