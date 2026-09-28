"""The dossier PDF (REQ-013; docs/design/dossier.md §6, §9).

Built from synthetic records made of this repository's own fixtures: the digital sample lease
(T028), the photographs with and without EXIF (T038), the Android export (T041), and a notice made
here. Every check reads the PDF back with pypdf, as a Tribunal clerk's software would. So a page
number is right only if that page really holds what the index says, and a digest is right only if
it is the SHA-256 of the fixture file.
"""

import hashlib
import io
import re
import uuid
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pdfs import HAZARDS, hostile
from tokelo.api.views import NOTICE
from tokelo.core import sources
from tokelo.core.model import (
    Capture,
    Clause,
    Document,
    DocumentKind,
    DocumentStatus,
    TimelineEntry,
    TimelineSource,
)
from tokelo.dossier import pdf, timeline
from tokelo.ocr import flags, rules

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LEASE = (FIXTURES / "leases" / "digital.pdf").read_bytes()
PHOTO_FULL = (FIXTURES / "photos" / "damp-full.jpg").read_bytes()
PHOTO_BARE = (FIXTURES / "photos" / "damp-bare.jpg").read_bytes()
EXPORT = (FIXTURES / "timeline" / "android.txt").read_bytes()

MISMATCH = "does not match the digest recorded when it was stored"
BUILT_AT = "2026-10-01T09:02:00Z"
DOSSIER = "44444444-4444-4444-8444-444444444444"


def a_notice(words: str = "NOTICE OF RENT INCREASE") -> bytes:
    out = io.BytesIO()
    drawing = canvas.Canvas(out, pagesize=A4)
    drawing.drawString(72, 720, words)
    drawing.showPage()
    drawing.save()
    return out.getvalue()


NOTICE_PDF = a_notice()


def document(
    kind: DocumentKind,
    data: bytes,
    content_type: str,
    requested_at: str,
    capture: Capture | None = None,
) -> Document:
    return Document(
        id=str(uuid.uuid4()),
        kind=kind,
        status=DocumentStatus.PROCESSED,
        s3_key=f"uploads/t/{kind}/x",
        content_type=content_type,
        size_bytes=len(data),
        requested_at=requested_at,
        s3_version_id="v1",
        sha256=hashlib.sha256(data).hexdigest(),
        stored_at=requested_at,
        capture=capture,
    )


def a_flagged_clause() -> Clause:
    """A clause flagged by a real rule of the catalogue: its explanation and sections are the
    ones a tenant is shown, not words made up for a test."""
    catalogue = rules.catalogue()
    rule = next(r for r in catalogue.rules if r.id == "deposit-no-interest")
    return Clause(
        ordinal=5,
        label="5",
        first_page=1,
        text="The deposit shall be held by the landlord and shall not earn interest.",
        flags=[flags.flag(rule, catalogue.version)],
    )


QUIET = Clause(ordinal=1, label="1", first_page=1, text="The parties to this lease are...")


class Case:
    """One dossier's worth of records: a lease, two photographs, a notice and an export."""

    def __init__(self, notice_matches: bool = True) -> None:
        self.lease = document(DocumentKind.LEASE, LEASE, "application/pdf", "2026-09-01T08:00:00Z")
        self.photo_full = document(
            DocumentKind.PHOTO,
            PHOTO_FULL,
            "image/jpeg",
            "2026-09-02T08:00:00Z",
            Capture(
                captured_at="2026-03-01T18:04:22+02:00",
                device="Samsung SM-A536B",
                latitude=-25.742,
                longitude=28.188,
            ),
        )
        self.photo_bare = document(
            DocumentKind.PHOTO, PHOTO_BARE, "image/jpeg", "2026-09-02T08:05:00Z"
        )
        self.notice = document(
            DocumentKind.NOTICE, NOTICE_PDF, "application/pdf", "2026-09-03T07:30:00Z"
        )
        self.export = document(DocumentKind.CHAT, EXPORT, "text/plain", "2026-09-20T12:00:00Z")
        self.flagged = a_flagged_clause()
        self.records = [
            pdf.Record(
                self.lease,
                matches=True,
                pdf=LEASE,
                clauses=(QUIET, self.flagged),
                unreadable_pages=(2,),
            ),
            pdf.Record(self.photo_full, matches=True, picture=pdf.picture(PHOTO_FULL)),
            pdf.Record(self.photo_bare, matches=True, picture=pdf.picture(PHOTO_BARE)),
            pdf.Record(self.notice, matches=notice_matches, pdf=NOTICE_PDF),
            pdf.Record(
                self.export,
                matches=True,
                messages=tuple(timeline.messages(EXPORT.decode())),
            ),
        ]
        self.entries = [
            TimelineEntry(
                id=self.photo_full.id,
                occurred_at="2026-03-01T16:04:22Z",
                source=TimelineSource.CAPTURE,
                summary="Photograph taken",
                document_id=self.photo_full.id,
            ),
            TimelineEntry(
                id=self.notice.id,
                occurred_at="2026-09-03T07:30:00Z",
                source=TimelineSource.NOTICE,
                summary=timeline.NOTICE_UPLOADED,
                document_id=self.notice.id,
            ),
            *timeline.chat_entries(self.export.id, EXPORT),
        ]

    def build(self) -> Dossier:
        out = io.BytesIO()
        built = pdf.build(DOSSIER, self.records, self.entries, BUILT_AT, out)
        return Dossier(built, out.getvalue())


class Dossier:
    def __init__(self, built: pdf.Built, data: bytes) -> None:
        self.built = built
        self.data = data
        self.reader = PdfReader(io.BytesIO(data))

    def page(self, number: int) -> str:
        """The page's words, one space between each, as a reader would search them."""
        return " ".join(self.reader.pages[number - 1].extract_text().split())

    def part(self, heading: str) -> str:
        """Every page of a part, from its first page to the next part's."""
        starts = sorted(self.built.parts.values())
        first = self.built.parts[heading]
        after = [s for s in starts if s > first]
        last = (after[0] - 1) if after else len(self.reader.pages)
        return " ".join(self.page(n) for n in range(first, last + 1))

    def index(self) -> str:
        return self.part("2. Index")


@pytest.fixture(scope="module")
def dossier() -> Dossier:
    return Case().build()


def flat(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------ order and the index ---
@pytest.mark.req("REQ-013")
def test_the_parts_come_in_order_each_where_the_index_says(dossier):
    parts = list(dossier.built.parts)

    assert parts == [
        "1. Cover",
        "2. Index",
        "3. Timeline",
        "4. The lease",
        "5. Evidence",
        "6. Communications",
        "7. The law cited",
        "8. Integrity",
    ]
    pages = list(dossier.built.parts.values())
    assert pages == sorted(pages) and pages[0] == 1
    for heading, page in dossier.built.parts.items():
        assert f"{heading} {page}" in dossier.index(), heading
        if heading != "1. Cover":
            assert dossier.page(page).startswith(heading) or heading in dossier.page(page)
    assert "Dispute dossier" in dossier.page(1)


@pytest.mark.req("REQ-013")
def test_every_record_is_on_the_page_the_index_gives(dossier):
    assert set(dossier.built.records) == {
        "Lease 1",
        "Photo 1",
        "Photo 2",
        "Notice 1",
        "WhatsApp export 1",
    }
    for name, page in dossier.built.records.items():
        assert f"{name} {page}" in dossier.index(), name
        assert name in dossier.page(page), name
    assert dossier.built.page_count == len(dossier.reader.pages)


@pytest.mark.req("REQ-013")
def test_the_pages_tokelo_wrote_are_numbered_and_the_copied_ones_are_left_as_they_are(dossier):
    """A lease's or a notice's own pages follow the page that introduces it, exactly as they
    were. Every other page is Tokelo's, and carries its number."""
    copied: dict[int, str] = {}
    for name, original in (("Lease 1", LEASE), ("Notice 1", NOTICE_PDF)):
        introduced = dossier.built.records[name]
        for n, page in enumerate(PdfReader(io.BytesIO(original)).pages, start=1):
            copied[introduced + n] = flat(page.extract_text())

    for number in range(1, dossier.built.page_count + 1):
        if number in copied:
            assert dossier.page(number) == copied[number], number
        else:
            assert f"Page {number}" in dossier.page(number), number


# ---------------------------------------------------------------- the cover ---
@pytest.mark.req("REQ-013")
def test_the_cover_says_what_this_is_and_how_to_check_a_file(dossier):
    cover = dossier.page(1)

    assert "Dispute dossier" in cover
    assert "Prepared with Tokelo" in cover
    assert "2026-10-01 11:02 SAST" in cover  # built at 09:02 UTC
    assert NOTICE in cover
    assert "sha256sum" in cover


# ------------------------------------------------------------- the timeline ---
@pytest.mark.req("REQ-012", "REQ-013")
def test_the_timeline_is_in_time_order_and_says_where_each_date_came_from(dossier):
    part = dossier.part("3. Timeline")

    photographed = part.index("2026-03-01 18:04")
    noticed = part.index("2026-09-03 09:30")
    first_message = part.index("2026-09-15 09:14")
    reply = part.index("2026-09-16 17:40")
    assert photographed < noticed < first_message < reply

    assert "capture time (EXIF)" in part
    # dossier.md §6: a date that is an upload time is labelled so, never passed off as when
    # the notice was served.
    assert "uploaded to Tokelo" in flat(part).replace("Uploaded", "uploaded")
    assert "read as SAST" in part
    assert "Thandi: Good morning" in part


# --------------------------------------------------------------- the lease ---
@pytest.mark.req("REQ-013")
def test_the_lease_is_its_own_pages_then_its_flagged_clauses(dossier):
    case_flag = a_flagged_clause().flags[0]
    part = dossier.part("4. The lease")

    assert "Lease 1" in part
    assert flat(PdfReader(io.BytesIO(LEASE)).pages[0].extract_text())[:60] in part
    assert flat(case_flag["explanation"]) in part
    for section in case_flag["sections"]:
        assert section["id"] in part
    # Only the flagged clause is in the table; the quiet one is the lease's own words, above.
    assert "The parties to this lease are" not in part
    # The page nobody could read is named, so the table isn't read as the whole lease.
    assert "couldn't read page 2" in part


# ------------------------------------------------------------- the evidence ---
@pytest.mark.req("REQ-009", "REQ-013")
def test_each_photo_shows_its_capture_details_digest_and_when_it_was_stored(dossier):
    case = Case()
    full = dossier.page(dossier.built.records["Photo 1"])
    bare = dossier.page(dossier.built.records["Photo 2"])

    assert "Captured: 2026-03-01 18:04 SAST" in full
    assert "Device: Samsung SM-A536B" in full
    assert "Location: -25.742, 28.188" in full
    assert f"SHA-256: {case.photo_full.sha256}" in full
    assert "Stored: 2026-09-02 10:00 SAST" in full

    for detail in ("Captured", "Device", "Location"):
        assert f"{detail}: not recorded" in bare
    assert f"SHA-256: {case.photo_bare.sha256}" in bare


@pytest.mark.req("REQ-013")
def test_each_photo_is_on_its_own_page_with_its_picture(dossier):
    for name in ("Photo 1", "Photo 2"):
        page = dossier.reader.pages[dossier.built.records[name] - 1]
        assert len(page.images) == 1, name


# ------------------------------------------------------- the communications ---
@pytest.mark.req("REQ-012", "REQ-013")
def test_the_notice_is_its_own_pages_and_the_export_its_messages_in_full(dossier):
    part = dossier.part("6. Communications")

    assert "NOTICE OF RENT INCREASE" in part
    assert "2026-09-16 17:40 · Mr Botha I will send someone next week." in part
    # A continuation line belongs to its message, as the export wrote it (evidence.md §6).
    assert "into the main bedroom" in part


@pytest.mark.req("REQ-013")
def test_a_long_message_is_in_the_communications_whole_and_on_the_timeline_cut():
    case = Case()
    long = "The ceiling is sagging. " * 40  # 960 characters, past the timeline's 500
    export = f"17/09/2026, 08:00 - Thandi: {long.strip()}\n".encode()
    case.records[4] = pdf.Record(
        case.export, matches=True, messages=tuple(timeline.messages(export.decode()))
    )
    case.entries = [e for e in case.entries if e.document_id != case.export.id]
    case.entries += timeline.chat_entries(case.export.id, export)

    built = case.build()

    assert flat(long) in built.part("6. Communications")
    assert flat(long) not in built.part("3. Timeline")


# ---------------------------------------------------------- the law cited ---
@pytest.mark.req("REQ-006", "REQ-013")
def test_the_law_cited_is_the_curated_text_of_each_section_the_flags_cite(dossier):
    part = dossier.part("7. The law cited")
    cited = [s["id"] for s in a_flagged_clause().flags[0]["sections"]]

    for section_id in cited:
        section = sources.section(section_id)
        assert section.id in part
        assert section.title in part
        # The section's own words, as curated: its first and last lines, reproduced.
        lines = [flat(line) for line in section.text.splitlines() if line.strip()]
        assert lines[0] in part and lines[-1] in part
    # Nothing else is cited: only what the flags rest on (REQ-006).
    others = sources.ids() - set(cited)
    assert not any(re.search(rf"\b{re.escape(i)}\b", part) for i in others)


# -------------------------------------------------------------- integrity ---
@pytest.mark.req("REQ-008", "REQ-013")
def test_integrity_lists_every_file_with_the_digest_of_the_fixture(dossier):
    part = dossier.part("8. Integrity")

    for data in (LEASE, PHOTO_FULL, PHOTO_BARE, NOTICE_PDF, EXPORT):
        assert hashlib.sha256(data).hexdigest() in part
    assert MISMATCH not in dossier.data.decode("latin-1")
    assert MISMATCH not in " ".join(dossier.page(n) for n in range(1, len(dossier.reader.pages)))


@pytest.mark.req("REQ-013")
def test_a_file_that_no_longer_matches_its_digest_is_still_in_and_marked():
    """dossier.md §4: hiding it would be worse than showing it."""
    built = Case(notice_matches=False).build()

    slip = built.page(built.built.records["Notice 1"])
    assert MISMATCH in slip
    assert "NOTICE OF RENT INCREASE" in built.part("6. Communications")
    assert MISMATCH in built.part("8. Integrity")
    elsewhere = [
        n
        for n in range(1, built.built.page_count + 1)
        if MISMATCH in built.page(n) and n != built.built.records["Notice 1"]
    ]
    assert all(n >= built.built.parts["8. Integrity"] for n in elsewhere)


# ------------------------------------------------------- what isn't there ---
@pytest.mark.req("REQ-013")
def test_a_part_with_nothing_selected_is_left_out_and_the_index_says_so():
    case = Case()
    case.records = [case.records[1]]  # one photograph
    case.entries = case.entries[:1]

    built = case.build()

    assert list(built.built.parts) == [
        "1. Cover",
        "2. Index",
        "3. Timeline",
        "5. Evidence",
        "8. Integrity",
    ]
    index = built.index()
    assert "4. The lease — none selected" in index
    assert "6. Communications — none selected" in index
    assert "7. The law cited — no lease selected" in index


@pytest.mark.req("REQ-013")
def test_a_notice_that_cant_be_opened_is_named_with_its_digest_not_dropped():
    case = Case()
    broken = b"%PDF-1.7 broken"
    case.records[3] = pdf.Record(case.notice, matches=True, pdf=broken)

    built = case.build()

    slip = built.page(built.built.records["Notice 1"])
    assert "couldn't be opened" in slip
    assert f"SHA-256: {case.notice.sha256}" in slip


@pytest.mark.req("REQ-013")
def test_a_photo_that_cant_be_shown_still_has_its_page_and_digest():
    case = Case()
    case.records[2] = pdf.Record(case.photo_bare, matches=True, picture=None)

    built = case.build()

    page = built.page(built.built.records["Photo 2"])
    assert "couldn't be shown" in page
    assert f"SHA-256: {case.photo_bare.sha256}" in page


@pytest.mark.req("REQ-013")
def test_copied_pages_carry_no_script_or_attachment():
    case = Case()
    case.records[3] = pdf.Record(case.notice, matches=True, pdf=hostile())

    built = case.build()

    for hazard in HAZARDS:
        assert hazard not in built.data, hazard
    assert "NOTICE TO VACATE THE PREMISES" in built.part("6. Communications")


# ------------------------------------------------------------- the pictures ---
def jpeg(size: tuple[int, int], orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (180, 120, 90))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    exif[0x0110] = "Samsung SM-A536B"  # Model: must not travel into the dossier's copy
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


@pytest.mark.req("REQ-013")
def test_a_large_photo_is_brought_down_to_150_dpi_on_the_page():
    picture = pdf.picture(jpeg((4000, 3000)))

    assert picture is not None
    width, height = pdf.PHOTO_BOX_PX
    assert picture.width <= width and picture.height <= height
    assert max(picture.width / width, picture.height / height) > 0.99  # fitted, not shrunk more
    assert abs(picture.width / picture.height - 4 / 3) < 0.01


def test_a_small_photo_is_not_enlarged():
    picture = pdf.picture(PHOTO_FULL)

    assert picture is not None and (picture.width, picture.height) == (640, 480)


def test_a_photo_taken_sideways_is_shown_upright():
    picture = pdf.picture(jpeg((400, 200), orientation=6))

    assert picture is not None and (picture.width, picture.height) == (200, 400)


def test_the_dossiers_copy_of_a_photo_carries_no_metadata():
    """The capture details the tenant chose to include are printed on the page. The copy of the
    picture carries none, so nothing leaves in the file that the page doesn't show."""
    picture = pdf.picture(jpeg((800, 600)))

    assert picture is not None
    assert dict(Image.open(io.BytesIO(picture.jpeg)).getexif()) == {}


def test_a_picture_with_transparency_is_flattened_onto_white():
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    out = io.BytesIO()
    image.save(out, "PNG")

    picture = pdf.picture(out.getvalue())

    assert picture is not None
    shown = Image.open(io.BytesIO(picture.jpeg)).convert("RGB")
    assert shown.getpixel((50, 50)) == pytest.approx((255, 255, 255), abs=2)


def test_what_isnt_a_picture_gives_none(monkeypatch):
    assert pdf.picture(b"not an image") is None
    monkeypatch.setattr(pdf, "MAX_PIXELS", 1000)
    assert pdf.picture(PHOTO_FULL) is None  # 640 x 480 is over a 1,000-pixel ceiling
