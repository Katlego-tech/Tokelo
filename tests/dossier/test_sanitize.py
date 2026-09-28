"""Copying a lease's or a notice's own pages into a dossier, without what could act (docs/design/
dossier.md §6 "Copying a PDF's pages in", §Threats).

A notice is whatever the landlord sent, and a PDF can carry more than pages: JavaScript run when
it opens, links that launch programs or open addresses, form fields, and files attached inside
it. The dossier goes to a Tribunal or a court, so it must carry none of that. What it keeps is
the page content, exactly as it was, because that is the evidence.

The hostile PDF is built here, with pypdf, so every hazard in it is one this test put there on
purpose.
"""

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject

from pdfs import HAZARDS, WORDS, hostile, plain_page
from tokelo.dossier import sanitize


def copied(data: bytes) -> bytes:
    """The pages as a dossier would hold them: sanitised, then written by a fresh writer."""
    writer = PdfWriter()
    for page in sanitize.pages(data):
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_the_fixture_really_carries_every_hazard():
    """Otherwise the test below would pass on a harmless file."""
    data = hostile()
    for hazard in HAZARDS:
        assert hazard in data, hazard


@pytest.mark.req("REQ-013")
def test_javascript_actions_forms_and_attachments_do_not_survive_the_copy():
    out = copied(hostile())

    for hazard in HAZARDS:
        assert hazard not in out, hazard


@pytest.mark.req("REQ-013")
def test_the_page_content_is_copied_as_it_is():
    out = PdfReader(io.BytesIO(copied(hostile())))

    assert len(out.pages) == 2
    assert f"{WORDS} - page 1" in out.pages[0].extract_text()
    assert f"{WORDS} - page 2" in out.pages[1].extract_text()


@pytest.mark.req("REQ-013")
def test_an_annotation_that_doesnt_act_keeps_its_place_without_an_action():
    (page, _) = sanitize.pages(hostile())

    annotations = page["/Annots"]
    assert isinstance(annotations, ArrayObject)
    kept = [a.get_object() for a in annotations]
    assert [a["/Subtype"] for a in kept] == ["/Text"]
    assert kept[0]["/Contents"] == "received 1 October"
    assert "/A" not in kept[0]


def test_a_clean_pdf_comes_through_unchanged_in_what_it_shows():
    out = PdfReader(io.BytesIO(copied(plain_page(pages=3))))

    assert [p.extract_text().strip() for p in out.pages] == [
        f"{WORDS} - page {n}" for n in (1, 2, 3)
    ]


def test_a_pdf_that_cant_be_opened_is_unreadable_not_an_error():
    with pytest.raises(sanitize.Unreadable):
        sanitize.pages(b"%PDF-1.7 this is not really a PDF")


def test_a_pdf_locked_with_a_password_is_unreadable():
    writer = PdfWriter(clone_from=io.BytesIO(plain_page()))
    writer.encrypt(user_password="landlord", owner_password="landlord")
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(sanitize.Unreadable):
        sanitize.pages(out.getvalue())


def test_a_pdf_with_only_an_owner_password_opens():
    """Many PDFs from an agency are 'protected' against editing, with no password to open them.
    Such a notice is readable, and its pages belong in the dossier."""
    writer = PdfWriter(clone_from=io.BytesIO(plain_page()))
    writer.encrypt(user_password="", owner_password="agency")
    out = io.BytesIO()
    writer.write(out)

    (page,) = sanitize.pages(out.getvalue())
    assert WORDS in page.extract_text()


@pytest.mark.parametrize("page_count", [1, 4])
def test_count_is_the_number_of_pages(page_count):
    assert sanitize.count(plain_page(pages=page_count)) == page_count


def test_the_numbered_types_survive_a_page_with_no_annotations():
    """A page's own number-valued entries are content, not hazards."""
    writer = PdfWriter(clone_from=io.BytesIO(plain_page()))
    writer.pages[0][NameObject("/Rotate")] = NumberObject(90)
    out = io.BytesIO()
    writer.write(out)

    (page,) = sanitize.pages(out.getvalue())
    assert page["/Rotate"] == 90
