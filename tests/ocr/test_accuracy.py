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

The test is marked expected-to-fail until T029 writes the reader. `strict=True`: the day it
reads, this passes, the suite goes red for an unexpected pass, and the marker comes off — so
nobody has to remember that the measurement exists.
"""

import time
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


def read_form(form: str, page: int) -> tuple[str, float]:
    """One page of one sample, and how long it took. The reader is T029's."""
    # T029 writes this module; until it does, the tests above are expected to fail.
    from tokelo.ocr import pages  # pyright: ignore[reportAttributeAccessIssue]

    if form == "photo":
        data, content_type = (LEASES / f"photo-{page}.jpg").read_bytes(), "image/jpeg"
        page_number = 1
    else:
        data, content_type = (LEASES / f"{form}.pdf").read_bytes(), "application/pdf"
        page_number = page

    started = time.monotonic()
    result = pages.read(data, content_type, page_number)
    return result.text, time.monotonic() - started


@pytest.mark.xfail(strict=True, reason="T029 hasn't written the reader yet")
@pytest.mark.req("NFR-005")
@pytest.mark.parametrize("form", ["digital", "scanned", "photo"])
def test_each_form_is_read_accurately_enough_to_check_its_clauses(form):
    known = known_pages()
    rates = []
    for number, expected in enumerate(known, start=1):
        text, _ = read_form(form, number)
        rates.append(character_error_rate(text, expected))

    worst = max(rates)
    assert worst <= ALLOWED[form], (
        f"{form}: worst page had a {worst:.1%} character error rate, "
        f"and NFR-005 allows {ALLOWED[form]:.0%}"
    )


@pytest.mark.xfail(strict=True, reason="T029 hasn't written the reader yet")
@pytest.mark.req("NFR-004")
@pytest.mark.parametrize("form", ["scanned", "photo"])
def test_a_page_is_read_inside_the_time_a_tenant_waits(form):
    """The scanned and photographed forms are the ones that reach Tesseract; the digital one is
    a text layer and costs nothing worth measuring."""
    for number in range(1, len(known_pages()) + 1):
        _, seconds = read_form(form, number)
        assert seconds < SECONDS_A_PAGE, (
            f"{form} page {number} took {seconds:.1f}s, and NFR-004 allows {SECONDS_A_PAGE}s"
        )


@pytest.mark.xfail(strict=True, reason="T029 hasn't written the reader yet")
@pytest.mark.req("REQ-004")
def test_the_reader_says_which_form_the_text_came_from():
    """A digital lease must be read from its text layer, not rendered and guessed at: it is
    exact, and it is free (ADR-0009)."""
    from tokelo.ocr import pages  # pyright: ignore[reportAttributeAccessIssue]

    digital = pages.read((LEASES / "digital.pdf").read_bytes(), "application/pdf", 1)
    assert digital.source == "text_layer"
    assert digital.readable is True

    photo = pages.read((LEASES / "photo-1.jpg").read_bytes(), "image/jpeg", 1)
    assert photo.source == "ocr"


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
