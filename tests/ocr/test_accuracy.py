"""How well the reader reads (NFR-004, NFR-005; ADR-0009; docs/design/ocr.md §9).

ADR-0009 chose the PDF's text layer first and Tesseract where there isn't one, and said the
choice would be measured rather than assumed. This is that measurement: the same lease in the
three forms tenants have it, each read back and compared with the text it was made from
(`tests/fixtures/leases/`).

Two numbers decide it:

* **character error rate** — how much of the page came back wrong. NFR-005 allows 5% on a scan
  and 15% on a phone photo, because a photo of a page on a kitchen table is a harder thing to
  read than a page through an office scanner.
* **seconds per page** — NFR-004 allows 30, which is what keeps a lease's flags inside the two
  minutes NFR-003 promises.

The reader runs inside the `ocr` image, where Tesseract 5.5.0 is (tests/ocr/conftest.py), so
these numbers are the engine that will read a tenant's lease and not whatever the machine running
the tests happens to have.

**The samples are synthetic.** They are a page of clean Helvetica, rendered, then degraded on
purpose — keystone, one-sided light, a shadow across the middle, soft focus and hard compression.
That is a floor, not a promise: a photograph of a creased, off-white lease under a kitchen light
is harder than anything here, and the day real samples exist these numbers should be read again
(T036 times a real lease end to end on staging).
"""

from pathlib import Path

import pytest

LEASES = Path(__file__).resolve().parents[1] / "fixtures" / "leases"
PAGE_BREAK = "--- page 2 ---"

# What each form is allowed to get wrong, and why they differ (NFR-005).
ALLOWED = {"digital": 0.01, "scanned": 0.05, "photo": 0.15}
SECONDS_A_PAGE = 30  # NFR-004


def known_pages() -> list[str]:
    """The text the samples were made from: the only thing here anybody wrote."""
    return [page.strip() for page in (LEASES / "lease.txt").read_text().split(PAGE_BREAK)]


def character_error_rate(read: str, known: str) -> float:
    """Levenshtein distance over the length of the known text.

    Whitespace is normalised first: a reader that wraps a line differently has not misread it,
    and the clause splitter (T031) works line by line anyway.
    """
    a, b = " ".join(read.split()), " ".join(known.split())
    previous = list(range(len(b) + 1))
    for i, from_read in enumerate(a, start=1):
        current = [i]
        for j, from_known in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (from_read != from_known),  # substitution
                )
            )
        previous = current
    return previous[-1] / max(1, len(b))


@pytest.mark.req("NFR-005")
@pytest.mark.parametrize("form", ["digital", "scanned", "photo"])
def test_each_form_is_read_accurately_enough_to_check_its_clauses(form, reader):
    known = known_pages()
    rates = []
    for number, expected in enumerate(known, start=1):
        rates.append(character_error_rate(reader(form, number)["text"], expected))

    worst = max(rates)
    assert worst <= ALLOWED[form], (
        f"{form}: worst page had a {worst:.1%} character error rate, "
        f"and NFR-005 allows {ALLOWED[form]:.0%}"
    )


@pytest.mark.req("NFR-004")
@pytest.mark.parametrize("form", ["scanned", "photo"])
def test_a_page_is_read_inside_the_time_a_tenant_waits(form, reader):
    """The scanned and photographed forms are the ones that reach Tesseract; the digital one is
    a text layer and costs nothing worth measuring."""
    for number in range(1, len(known_pages()) + 1):
        seconds = reader(form, number)["seconds"]
        assert seconds < SECONDS_A_PAGE, (
            f"{form} page {number} took {seconds:.1f}s, and NFR-004 allows {SECONDS_A_PAGE}s"
        )


@pytest.mark.req("REQ-004")
def test_the_reader_says_which_form_the_text_came_from(reader):
    """A digital lease must be read from its text layer, not rendered and guessed at: it is
    exact, and it is free (ADR-0009)."""
    digital = reader("digital", 1)
    assert digital["source"] == "text_layer"
    assert digital["readable"] is True
    assert reader("photo", 1)["source"] == "ocr"


def test_the_samples_are_the_lease_that_was_written():
    """Not about the reader: about the fixtures. If `lease.txt` and the built forms drift apart,
    every number above becomes meaningless, so the pages and their clauses are checked here.

    This one is not expected to fail — it is the ground the others stand on.
    """
    known = known_pages()
    assert len(known) == 2, "the sample lease is two pages"
    assert (LEASES / "digital.pdf").exists() and (LEASES / "scanned.pdf").exists()
    assert (LEASES / "photo-1.jpg").exists() and (LEASES / "photo-2.jpg").exists()
    assert "4.2 The deposit shall not bear interest" in known[0]
    assert "7.2 The landlord may evict the tenant without recourse" in known[1]
