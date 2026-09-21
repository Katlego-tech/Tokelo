"""Accepting or refusing an uploaded file (REQ-003; docs/design/ocr.md §4, §Threats).

REQ-003 is checked twice, and the two checks see different things.

* **When the URL is asked for** (`api/uploads.py`, tests/api/test_presign.py) only the tenant's
  claim is available — a kind, a content type and a size — so that is what is checked, and the
  answer is a policy S3 itself enforces.
* **When the worker picks the object up** the bytes are there. That is the check held here: the
  file's real type, read out of its first few bytes, and a PDF's page count, which no policy can
  count.

The second check is not a repeat of the first. A file renamed to `.pdf` passes the first and
fails here, which is the point (ocr.md §Threats, "A file renamed to look like a PDF or photo").
"""

import io
import struct
import zlib
from pathlib import Path

import pytest

from tokelo.core.model import DocumentKind
from tokelo.ocr import intake

LEASES = Path(__file__).resolve().parents[1] / "fixtures" / "leases"
MEGABYTE = 1024 * 1024


def pdf_of(pages: int) -> bytes:
    """A real PDF of `pages` blank A4 pages — enough for anything counting them."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def png_claiming(width: int, height: int) -> bytes:
    """A PNG header that says it is enormous, and no pixels behind it.

    A decompression bomb is this: a few hundred bytes that ask a reader to allocate gigabytes.
    Only the header is needed, because a reader that is going to fall for it falls for it there.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)


@pytest.mark.req("REQ-003")
def test_a_lease_pdf_is_accepted_and_counted():
    """The ordinary case: a two-page lease from an agent, and the page count the fan-out needs."""
    accepted = intake.accept(DocumentKind.LEASE, (LEASES / "digital.pdf").read_bytes())
    assert accepted.content_type == "application/pdf"
    assert accepted.pages == 2


@pytest.mark.req("REQ-003")
def test_a_photographed_page_is_accepted_as_one_page():
    """A tenant with no printer photographs the lease. One photo is one page (ocr.md §4)."""
    accepted = intake.accept(DocumentKind.LEASE, (LEASES / "photo-1.jpg").read_bytes())
    assert accepted.content_type == "image/jpeg"
    assert accepted.pages == 1


@pytest.mark.req("REQ-003")
def test_the_type_is_read_from_the_bytes_and_not_from_what_was_claimed():
    """ocr.md §Threats. The upload declared a content type and S3 stored it on the object; both
    are the uploader's word. The first bytes of the file are not."""
    assert intake.type_of(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n") == "application/pdf"
    assert intake.type_of((LEASES / "photo-1.jpg").read_bytes()) == "image/jpeg"
    assert intake.type_of(png_claiming(8, 8)) == "image/png"
    assert intake.type_of(b"PK\x03\x04\x14\x00\x06\x00") is None, "a .docx is a zip"


@pytest.mark.req("REQ-003")
def test_a_file_renamed_to_look_like_a_lease_is_refused_with_the_reason():
    """A .docx renamed .pdf gets past the policy — its Content-Type header is whatever the
    browser was told to send. It does not get past the bytes."""
    docx = b"PK\x03\x04\x14\x00\x06\x00\x08\x00" + b"\x00" * 200
    with pytest.raises(intake.Refused) as refusal:
        intake.accept(DocumentKind.LEASE, docx)
    assert "PDF" in str(refusal.value) and "JPEG" in str(refusal.value)


@pytest.mark.req("REQ-003")
def test_a_lease_longer_than_the_limit_is_refused():
    """REQ-003 allows 30 pages. A 31-page PDF is refused before a single page is rendered, which
    is also what keeps a crafted PDF from spending the worker's fifteen minutes."""
    with pytest.raises(intake.Refused) as refusal:
        intake.accept(DocumentKind.LEASE, pdf_of(intake.PAGES + 1))
    assert "30 pages" in str(refusal.value)


@pytest.mark.req("REQ-003")
def test_a_lease_of_exactly_the_limit_is_accepted():
    """The boundary belongs to the tenant: 30 is allowed, and it is the 31st that is refused."""
    assert intake.accept(DocumentKind.LEASE, pdf_of(intake.PAGES)).pages == intake.PAGES


@pytest.mark.req("REQ-003")
def test_a_file_over_the_size_limit_is_refused():
    """S3's policy already refuses this one, so it can only arrive by some other route. It is
    still refused, and refused before anything tries to parse 21 MB of it."""
    with pytest.raises(intake.Refused) as refusal:
        intake.accept(DocumentKind.LEASE, b"%PDF-1.7\n" + b"\x00" * (21 * MEGABYTE))
    assert "20 MB" in str(refusal.value)


@pytest.mark.req("REQ-003")
def test_an_empty_file_is_refused():
    with pytest.raises(intake.Refused):
        intake.accept(DocumentKind.LEASE, b"")


@pytest.mark.req("REQ-003")
def test_a_pdf_that_cannot_be_opened_is_refused_rather_than_raising():
    """A truncated upload, or a PDF built by something broken. The worker must say so to the
    tenant; a worker that raises here sends the job round three times to no purpose (ADR-0007)."""
    with pytest.raises(intake.Refused) as refusal:
        intake.accept(DocumentKind.LEASE, b"%PDF-1.7\nnot actually a PDF\n%%EOF\n")
    assert "couldn't be opened" in str(refusal.value)


@pytest.mark.req("REQ-003")
def test_an_image_that_asks_for_gigabytes_is_refused():
    """ocr.md §Threats: a decompression bomb. 30000 x 30000 is 900 million pixels from a file of
    a few hundred bytes, and the worker has 3 GB."""
    with pytest.raises(intake.Refused):
        intake.accept(DocumentKind.LEASE, png_claiming(30_000, 30_000))


@pytest.mark.req("REQ-003")
def test_an_image_that_does_not_decode_is_refused():
    """The first bytes say PNG and the rest is nothing. Refused here, rather than found by
    Tesseract two steps later with no reason to give the tenant."""
    with pytest.raises(intake.Refused):
        intake.accept(DocumentKind.LEASE, b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


@pytest.mark.req("REQ-003")
def test_each_kind_takes_what_the_contract_says_it_takes():
    """api.md §6's table, from the other side. A photo of a room is not a PDF, and a WhatsApp
    export is not a photo."""
    with pytest.raises(intake.Refused):
        intake.accept(DocumentKind.PHOTO, (LEASES / "digital.pdf").read_bytes())

    export = "[2026/03/01, 18:04] Tenant: the geyser is leaking again\n" * 20
    assert intake.accept(DocumentKind.CHAT, export.encode()).content_type == "text/plain"

    with pytest.raises(intake.Refused):
        intake.accept(DocumentKind.CHAT, (LEASES / "photo-1.jpg").read_bytes())


@pytest.mark.req("REQ-003")
def test_both_checks_read_one_table():
    """The two halves of REQ-003 have to agree, or a file the API promised to take is refused
    after it has been uploaded. They agree by reading the same table, not by matching lists."""
    from tokelo.api import uploads

    assert uploads.KINDS is intake.KINDS
    assert intake.KINDS[DocumentKind.LEASE].size == 20 * MEGABYTE
    assert intake.KINDS[DocumentKind.LEASE].types == frozenset(
        {"application/pdf", "image/jpeg", "image/png"}
    )
