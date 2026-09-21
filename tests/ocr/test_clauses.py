"""Splitting a lease into clauses (REQ-005; docs/design/ocr.md §6, "Splitting into clauses").

A flag is shown against a clause, so the split decides what a tenant is shown. Too eager and one
clause becomes three fragments none of which reads as a sentence; too lazy and a whole page
arrives as one block with a flag floating somewhere in it.

The sample lease (T028) is the test: it is the shape a South African residential lease actually
has — numbered sections with numbered subclauses, headings in capitals, and a preamble before
any of it."""

from pathlib import Path

import pytest

from tokelo.ocr import clauses

LEASES = Path(__file__).resolve().parents[1] / "fixtures" / "leases"
PAGE_BREAK = "--- page 2 ---"


@pytest.fixture
def lease() -> list[str]:
    return [page.strip() for page in (LEASES / "lease.txt").read_text().split(PAGE_BREAK)]


@pytest.mark.req("REQ-005")
def test_the_sample_lease_splits_into_its_numbered_clauses(lease):
    split = clauses.split(lease)
    labels = [clause.label for clause in split]

    assert labels[0] == "Preamble", "what comes before the first number is clause 0"
    for expected in ("1.1", "2.2", "3.3", "4.2", "5.1", "6.1", "7.1", "7.2", "8.1", "9.1"):
        assert expected in labels, f"{expected} was not found as a clause"
    assert labels == sorted(set(labels), key=labels.index), "a label appears twice"


@pytest.mark.req("REQ-005")
def test_each_clause_keeps_its_number_its_page_and_its_text(lease):
    split = {clause.label: clause for clause in clauses.split(lease)}

    deposit = split["4.2"]
    assert deposit.first_page == 1
    assert (
        deposit.text
        == "4.2 The deposit shall not bear interest and no interest shall be payable to the tenant."
    )

    eviction = split["7.2"]
    assert eviction.first_page == 2, "a clause knows the page it starts on"
    assert "without recourse to a court of law" in eviction.text


@pytest.mark.req("REQ-005")
def test_a_clause_that_runs_over_a_line_stays_one_clause(lease):
    """A lease wraps mid-sentence. The continuation belongs to the clause above it, not to a new
    one, or a rule would see half a sentence and miss what it says."""
    split = {clause.label: clause for clause in clauses.split(lease)}
    assert "less any amounts the landlord considers due" in split["4.3"].text
    assert split["4.3"].text.count("4.3") == 1


@pytest.mark.req("REQ-005")
def test_a_heading_in_capitals_belongs_to_the_clause_under_it(lease):
    """ "7. BREACH" is a heading, not a clause of its own: its words are part of what follows, so
    a tenant reading a flag sees what part of the lease it came from."""
    split = {clause.label: clause for clause in clauses.split(lease)}
    assert "BREACH" in split["7.1"].text
    assert "BREACH" not in split["8.1"].text
    assert "7" not in {clause.label for clause in clauses.split(lease)}, (
        "a bare section number with only a heading is not a clause"
    )


@pytest.mark.req("REQ-005")
def test_the_clauses_come_back_in_the_order_they_were_written(lease):
    ordinals = [clause.ordinal for clause in clauses.split(lease)]
    assert ordinals == sorted(ordinals)
    assert ordinals[0] == 0, "the preamble is clause 0"


@pytest.mark.req("REQ-005")
@pytest.mark.parametrize(
    ("line", "label"),
    [
        ("12. The tenant shall pay the rent.", "12"),
        ("12.3 The tenant shall pay the rent.", "12.3"),
        ("12.3.1 The tenant shall pay the rent.", "12.3.1"),
        ("(a) The tenant shall pay the rent.", "(a)"),
        ("Clause 12 The tenant shall pay the rent.", "Clause 12"),
        ("(iv) The tenant shall pay the rent.", "(iv)"),
    ],
)
def test_the_shapes_a_clause_number_takes(line, label):
    """ocr.md §6 lists the forms; this holds the splitter to them."""
    split = clauses.split([line])
    assert [clause.label for clause in split] == [label]


@pytest.mark.req("REQ-005")
def test_something_that_is_not_a_clause_number_does_not_start_a_clause():
    """A lease is full of numbers that begin a line and mean nothing: an amount, a date, an
    address. Treating one as a clause would cut a sentence in half."""
    lines = [
        "1. RENTAL",
        "1.1 The rental is R6 500 per month, payable monthly in advance.",
        "R500 is payable for late payment.",
        "28 February 2027 is the last day of the lease.",
        "14B Marabastad Road is the address of the dwelling.",
    ]
    split = clauses.split([lines[0] + "\n" + "\n".join(lines[1:])])
    assert [clause.label for clause in split] == ["1.1"]
    assert "R500 is payable" in split[0].text


@pytest.mark.req("REQ-005")
def test_a_page_that_could_not_be_read_contributes_nothing(lease):
    """An unreadable page is reported by its number and left out (REQ-004); the clauses around
    it must still be found, and must not be joined across the hole."""
    split = clauses.split([lease[0], "", lease[1]])
    labels = [clause.label for clause in split]
    assert "5.1" in labels and "6.1" in labels
    assert split[labels.index("6.1")].first_page == 3
