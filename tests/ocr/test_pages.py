"""The reader's behaviour (REQ-004; ADR-0009; docs/design/ocr.md §4).

The accuracy of what it reads is measured next door in test_accuracy.py. What is held here is
what it *does*: which route a page takes, and what happens to a page nobody could read.
"""

import pytest

from tokelo.ocr import pages


@pytest.mark.req("REQ-004")
def test_a_lease_that_already_carries_its_words_is_not_put_through_tesseract(reader):
    """ADR-0009's first line. A PDF from an agent has its text; taking it is exact, instant and
    free, and rendering it to guess at the same words would be all three of the opposites."""
    first = reader("digital", 1)
    assert first["source"] == "text_layer"
    assert "RESIDENTIAL LEASE AGREEMENT" in first["text"]
    assert first["seconds"] < 5, "reading a text layer should cost almost nothing"


@pytest.mark.req("REQ-004")
def test_a_scan_has_no_text_to_take_so_it_is_read(reader):
    """The same lease through a scanner is pixels. It has to be read, and it is."""
    page = reader("scanned", 2)
    assert page["source"] == "ocr"
    assert page["readable"] is True
    assert "BREACH" in page["text"]


@pytest.mark.req("REQ-004")
def test_a_page_nobody_could_read_is_reported_as_such_rather_than_guessed_at(reader):
    """A photograph taken in the dark while moving. What comes back is specks, and the tenant is
    told this page failed — not shown a clause assembled out of noise."""
    page = reader("unreadable", 1)
    assert page["source"] == "ocr"
    assert page["readable"] is False


@pytest.mark.req("REQ-003")
def test_the_reader_can_say_how_long_a_lease_is(reader):
    """What T030 checks a lease against: REQ-003 allows 30 pages."""
    assert reader("count", "digital") == {"pages": 2}


def test_a_page_that_is_not_in_the_document_is_empty_rather_than_an_error(reader):
    """A redelivered job for a page that no longer exists must not crash the worker; it has
    nothing to say, and says nothing (ADR-0007)."""
    assert reader("digital", 9)["readable"] is False


@pytest.mark.req("REQ-004")
def test_what_is_read_keeps_the_lines_the_clause_splitter_needs():
    """`tidy` runs on this machine, not in the image: it is only text. The splitter reads line
    by line (clauses.py), so trailing spaces and runs of blank lines go and the breaks stay."""
    tidied = pages.tidy("4.1 The tenant shall pay   \n\n\n\n4.2 The deposit shall not  \n")
    assert tidied == "4.1 The tenant shall pay\n\n4.2 The deposit shall not"


@pytest.mark.req("REQ-004")
def test_noise_is_not_mistaken_for_a_page_of_a_lease():
    """What separates a read page from a failed one: enough characters, and enough of them in
    words. Both, because either alone lets something through."""
    assert pages.is_a_page("4.1 " + "The tenant shall pay the rent on the first day. " * 4)
    assert not pages.is_a_page("")
    assert not pages.is_a_page("|.  ,,  '' ~~ .. || ;; -- .. '' ,, |||| .... '''' ~~~~ ;;;;")
    assert not pages.is_a_page("1234567890 " * 40), "digits alone are not a page of a lease"
