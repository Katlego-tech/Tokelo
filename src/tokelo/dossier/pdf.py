"""The dossier PDF (docs/design/dossier.md §6; REQ-013).

One file a tenant can hand to the Rental Housing Tribunal or the Small Claims Court, in eight
parts:
1. the cover
2. the index
3. the timeline
4. the lease
5. the evidence
6. the communications
7. the law the lease's flags cite
8. every file's digest

It claims no conformance with either forum's filing rules: nobody has obtained them yet
(dossier.md §10).

**It shows what was stored, and says so.** Each photograph carries its capture details, or "not
recorded". Each file carries its SHA-256, and a file that no longer matches its digest is marked
in red rather than left out. Each timeline date says where it came from. The law is the curated
text, reproduced, never paraphrased (REQ-006).

**How it's put together.** Tokelo writes its own pages with ReportLab: the cover, the index, the
timeline, each record's pages, the law and the integrity table. It copies the lease's and the
notices' own pages in with pypdf, sanitised ([sanitize.py](sanitize.py)) and otherwise as they
are. Its own pages are numbered at the foot. The copied ones aren't touched, but they count.
Every part but the index is rendered once, in order, so each knows the page it starts on. The
index, which needs every other part's page, is rendered twice: first to learn how many pages it
takes, then with the numbers.

**Records are named in Tokelo's own terms**: "Lease 1", "Photo 2", "Notice 1", "WhatsApp export
1". Tokelo keeps no file names (api.md §6), and a name that invented a description would be a
claim about the evidence. Within each kind the first is the earliest by the timeline, then by
upload order, which is also the order each part shows them in: the records in time order
(REQ-013).
"""

import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, BinaryIO
from xml.sax.saxutils import escape

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    LongTable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import Image as Drawn

from tokelo.api.views import NOT_RECORDED, NOTICE
from tokelo.core import sources
from tokelo.core.model import Clause, Document, DocumentKind, TimelineEntry, TimelineSource
from tokelo.dossier import sanitize, timeline

# ------------------------------------------------------------------- the page ---
PAGE = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 20 * mm
FRAME_WIDTH = PAGE[0] - 2 * MARGIN_X

# dossier.md §6: a photo fitted to A4 at up to 150 dpi. The box is what is left of the page
# under a photo's details. A photo is brought down to fill it at 150 dpi, never beyond, and
# never enlarged: a small photo is shown larger than 150 dpi would make it, from its own pixels.
DPI = 150
PHOTO_BOX = (FRAME_WIDTH, 150 * mm)
PHOTO_BOX_PX = (round(PHOTO_BOX[0] / 72 * DPI), round(PHOTO_BOX[1] / 72 * DPI))
# More pixels than this, even after JPEG's reduced decoding, is not a photograph a phone takes:
# decoding it could take the function's memory with it.
MAX_PIXELS = 60_000_000

INK = colors.HexColor("#1B1F24")
MUTED = colors.HexColor("#5B6470")
RED = colors.HexColor("#B42318")
RULE = colors.HexColor("#D0D5DD")
SHADE = colors.HexColor("#F2F4F7")

MISMATCH = "This file does not match the digest recorded when it was stored."

PARTS = (
    "1. Cover",
    "2. Index",
    "3. Timeline",
    "4. The lease",
    "5. Evidence",
    "6. Communications",
    "7. The law cited",
    "8. Integrity",
)
# The part each kind of record is shown in.
PART_OF = {
    DocumentKind.LEASE: "4. The lease",
    DocumentKind.PHOTO: "5. Evidence",
    DocumentKind.NOTICE: "6. Communications",
    DocumentKind.CHAT: "6. Communications",
}
KIND_NAMES = {
    DocumentKind.LEASE: "Lease",
    DocumentKind.PHOTO: "Photo",
    DocumentKind.NOTICE: "Notice",
    DocumentKind.CHAT: "WhatsApp export",
}
# Where a timeline entry's date came from, in the words the dossier shows (dossier.md §6).
DATED_BY = {
    TimelineSource.CAPTURE: "The photograph's own capture time (EXIF)",
    TimelineSource.CHAT_MESSAGE: "The export's own time, read as SAST",
}
NOTICE_DATED_BY = {
    timeline.NOTICE_PHOTOGRAPHED: "When the notice was photographed (EXIF)",
    timeline.NOTICE_CREATED: "The PDF's own creation date",
    timeline.NOTICE_UPLOADED: (
        "Uploaded to Tokelo on this date: the file carries no date of its own"
    ),
}


@dataclass(frozen=True)
class Picture:
    """A photograph as the dossier holds it: upright, fitted, re-encoded, and without metadata."""

    jpeg: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Record:
    """One selected document, with what the dossier shows of it. `matches` says whether the stored
    bytes still hash to the digest recorded at upload.

    What a kind carries:
    - a lease or a notice uploaded as a PDF: `pdf`, its own bytes, copied in sanitised
    - a photo, or a lease or notice uploaded as a photograph: `picture`. None when it can't be
      shown
    - a lease: `clauses` and `unreadable_pages`
    - a chat export: `messages`, parsed again from the file so each is whole (the timeline cuts
      them to 500 characters)
    """

    document: Document
    matches: bool
    pdf: bytes | None = None
    picture: Picture | None = None
    clauses: tuple[Clause, ...] = ()
    unreadable_pages: tuple[int, ...] = ()
    messages: tuple[timeline.Message, ...] = ()


@dataclass(frozen=True)
class Built:
    """What was built: its pages, and where each part and each record starts."""

    page_count: int
    parts: dict[str, int]
    records: dict[str, int]


@dataclass
class _Segment:
    """A run of pages: Tokelo's own, rendered from what `make` builds, or a PDF's own, copied in.

    `make` builds the flowables only when the segment is rendered, and ReportLab consumes the
    list as it places them. So a part's flowables exist only while that part is laid out: a
    5 MB export's 43,000 messages and timeline entries are never all held at once.
    """

    part: str
    record: str | None = None
    make: Callable[[], list[Flowable]] | None = None
    pdf: bytes | None = None
    rendered: bytes = b""
    pages: int = 0
    first: int = 0
    # Drawn at the top of every page after the segment's first, in room kept for it.
    running: Callable[[Canvas], None] | None = None


# --------------------------------------------------------------- the pictures ---
def picture(data: bytes) -> Picture | None:
    """A photograph fitted to the photo box at 150 dpi, upright, flattened onto white, and
    re-encoded without its EXIF. None when the bytes aren't a picture that can be shown safely.

    A JPEG is decoded at a reduced scale when that is still enough for the box, so a 50-megapixel
    photograph costs a fraction of its full size in memory."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            longest = max(PHOTO_BOX_PX)
            image.draft("RGB", (longest, longest))  # JPEG only; others ignore it
            if image.width * image.height > MAX_PIXELS:
                return None
            upright = ImageOps.exif_transpose(image) or image
            shown = _flattened(upright)
            shown.thumbnail(PHOTO_BOX_PX)
            out = io.BytesIO()
            shown.save(out, "JPEG", quality=85, optimize=True)
            return Picture(out.getvalue(), shown.width, shown.height)
    except Exception:
        # A stranger's bytes: Pillow can refuse them in many ways. Each means this file has no
        # picture to show, and its page says so, with its digest.
        return None


def _flattened(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        white = Image.new("RGB", rgba.size, (255, 255, 255))
        white.paste(rgba, mask=rgba.getchannel("A"))
        return white
    return image.convert("RGB")


# ------------------------------------------------------------------ building ---
def build(
    dossier_id: str,
    records: Sequence[Record],
    entries: Iterable[TimelineEntry],
    built_at: str,
    out: BinaryIO,
) -> Built:
    """The dossier, written to `out`. `entries` are the selected records' timeline entries."""
    _fonts()
    uploaded = {r.document.id: r.document.requested_at for r in records}
    ordered_entries = timeline.ordered(entries, uploaded)
    earliest: dict[str, str] = {}
    for entry in ordered_entries:
        earliest.setdefault(entry.document_id, timeline.utc(entry.occurred_at))
    in_order = sorted(
        records,
        key=lambda r: (
            earliest.get(r.document.id, "~"),  # undated records after the dated ones
            r.document.requested_at,
            r.document.id,
        ),
    )
    names = _names(in_order)
    entries_of: dict[str, list[TimelineEntry]] = {}
    for entry in ordered_entries:
        entries_of.setdefault(entry.document_id, []).append(entry)

    def of(kind: DocumentKind) -> list[Record]:
        return [r for r in in_order if r.document.kind is kind]

    leases, photos = of(DocumentKind.LEASE), of(DocumentKind.PHOTO)
    communications = of(DocumentKind.NOTICE) + of(DocumentKind.CHAT)
    cited = _cited(leases)

    segments: list[_Segment] = [
        _Segment(
            "3. Timeline",
            make=lambda: _timeline(ordered_entries, names),
            running=_running_headings if ordered_entries else None,
        ),
    ]
    for lease in leases:
        segments += _document_segments("4. The lease", lease, names, entries_of)
        segments.append(_Segment("4. The lease", make=lambda lease=lease: _flags(lease, names)))
    for photo in photos:
        segments += _document_segments("5. Evidence", photo, names, entries_of)
    for record in communications:
        segments += _document_segments("6. Communications", record, names, entries_of)
    if leases:
        segments.append(_Segment("7. The law cited", make=lambda: _law(cited)))
    segments.append(_Segment("8. Integrity", make=lambda: _integrity(in_order, names)))

    cover = _Segment("1. Cover", make=lambda: _cover(dossier_id, built_at, in_order))
    _render(cover, first=1)
    index = _Segment("2. Index")
    present = {s.part for s in segments}
    in_part: dict[str, list[str]] = {}
    for record in [*leases, *photos, *communications]:
        in_part.setdefault(PART_OF[record.document.kind], []).append(names[record.document.id])
    index.make = lambda: _index({}, present, in_part, dry_run=True)
    _render(index, first=1 + cover.pages)
    estimated = index.pages

    page = 1 + cover.pages + index.pages
    for segment in segments:
        if segment.make is not None:
            _render(segment, first=page)
        else:
            segment.first, segment.pages = page, sanitize.count(segment.pdf or b"")
        page += segment.pages

    parts: dict[str, int] = {"1. Cover": 1, "2. Index": 1 + cover.pages}
    starts: dict[str, int] = {}
    for segment in segments:
        parts.setdefault(segment.part, segment.first)
        if segment.record is not None:
            starts.setdefault(segment.record, segment.first)
    index.make = lambda: _index({**parts, **starts}, present, in_part, dry_run=False)
    _render(index, first=1 + cover.pages)
    if index.pages != estimated:
        raise RuntimeError("the index changed length once its page numbers were filled in")

    writer = PdfWriter()
    for segment in [cover, index, *segments]:
        if segment.make is not None:
            for rendered in PdfReader(io.BytesIO(segment.rendered)).pages:
                writer.add_page(rendered)
        else:
            for copied in sanitize.pages(segment.pdf or b""):
                writer.add_page(copied)
    writer.add_metadata({"/Title": "Dispute dossier", "/Creator": "Tokelo"})
    writer.write(out)
    ordered_parts = {p: parts[p] for p in PARTS if p in parts}
    return Built(page_count=page - 1, parts=ordered_parts, records=starts)


def _names(records: Sequence[Record]) -> dict[str, str]:
    """Each record's name in Tokelo: its kind and its place among that kind (module docstring)."""
    counted: dict[DocumentKind, int] = {}
    names: dict[str, str] = {}
    for record in records:
        kind = record.document.kind
        counted[kind] = counted.get(kind, 0) + 1
        names[record.document.id] = f"{KIND_NAMES[kind]} {counted[kind]}"
    return names


def _cited(leases: Sequence[Record]) -> list[str]:
    """The IDs of every section the leases' flags rest on, each once, in the order of the IDs."""
    found = {
        section["id"]
        for lease in leases
        for clause in lease.clauses
        for flag in clause.flags
        for section in flag.get("sections", [])
    }
    return sorted(found)


# ------------------------------------------------------------------ rendering ---
def _render(segment: _Segment, first: int) -> None:
    """Tokelo's own pages for `segment`, numbered from `first`."""
    out = io.BytesIO()
    last = [0]

    def later(canvas: Canvas, template: Any) -> None:
        if segment.running is not None:
            segment.running(canvas)
        foot(canvas, template)

    def foot(canvas: Canvas, _: Any) -> None:
        number = first + canvas.getPageNumber() - 1
        last[0] = canvas.getPageNumber()
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, 13 * mm, PAGE[0] - MARGIN_X, 13 * mm)
        canvas.setFont("Vera", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X, 9 * mm, f"Dispute dossier · {NOTICE}")
        canvas.drawRightString(PAGE[0] - MARGIN_X, 9 * mm, f"Page {number}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        out,
        pagesize=PAGE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP + (HEADINGS_ROOM if segment.running else 0),
        bottomMargin=MARGIN_BOTTOM,
        title="Dispute dossier",
        author="Tokelo",
        creator="Tokelo",
    )
    # Handed over, not copied: ReportLab pops each flowable as it places it (see _Segment).
    document.build(segment.make() if segment.make else [], onFirstPage=foot, onLaterPages=later)
    segment.rendered, segment.pages, segment.first = out.getvalue(), last[0], first


@cache
def _fonts() -> None:
    """Bitstream Vera, which ReportLab ships: a TrueType face with the curly quotes and dashes the
    statutes use. A character it lacks (an emoji in a chat) shows as an empty box rather than
    stopping the build."""
    from reportlab.lib.fonts import addMapping

    for name, file in (
        ("Vera", "Vera.ttf"),
        ("Vera-Bold", "VeraBd.ttf"),
        ("Vera-Italic", "VeraIt.ttf"),
        ("Vera-BoldItalic", "VeraBI.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, file))
    addMapping("Vera", 0, 0, "Vera")
    addMapping("Vera", 1, 0, "Vera-Bold")
    addMapping("Vera", 0, 1, "Vera-Italic")
    addMapping("Vera", 1, 1, "Vera-BoldItalic")


def _style(
    name: str,
    size: float,
    leading: float,
    font: str = "Vera",
    color: colors.Color = INK,
    **more: Any,
) -> ParagraphStyle:
    return ParagraphStyle(
        name, fontName=font, fontSize=size, leading=leading, textColor=color, **more
    )


TITLE = _style("title", 24, 29, font="Vera-Bold", spaceAfter=4)
HEADING = _style("heading", 15, 19, font="Vera-Bold", spaceAfter=8)
SUBHEADING = _style("subheading", 11, 14, font="Vera-Bold", spaceBefore=8, spaceAfter=4)
BODY = _style("body", 9.5, 13.5, spaceAfter=5)
SMALL = _style("small", 8, 11, color=MUTED, spaceAfter=3)
CELL = _style("cell", 8, 10.5)
CELL_MUTED = _style("cell_muted", 8, 10.5, color=MUTED)
CELL_RED = _style("cell_red", 8, 10.5, color=RED)
INDENTED = _style("indented", 8, 10.5, leftIndent=12)
WARNING = _style("warning", 9.5, 13, font="Vera-Bold", color=RED, spaceAfter=5)
QUOTE = _style("quote", 9, 12.5, color=MUTED, leftIndent=10, spaceAfter=5)
NOTICE_BOX = _style("notice", 10.5, 14, font="Vera-Bold")
MESSAGE = _style("message", 9, 12.5, spaceAfter=6)


def _text(value: str) -> str:
    """Anyone's words, safe for ReportLab's paragraph markup: escaped, with line breaks kept and
    control characters dropped."""
    kept = "".join(c for c in value if c in "\n\t" or ord(c) >= 32)
    return escape(kept).replace("\n", "<br/>")


def _para(value: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(_text(value), style)


def _sast(when: str) -> str:
    return timeline.in_sast(when)


def _size(size: int) -> str:
    return f"{size:,} bytes"


# ------------------------------------------------------------------- the parts ---
def _cover(dossier_id: str, built_at: str, records: Sequence[Record]) -> list[Flowable]:
    counts = {kind: sum(r.document.kind is kind for r in records) for kind in KIND_NAMES}
    listed = [
        f"{n} {_lowered(KIND_NAMES[kind])}{'s' if n != 1 else ''}"
        for kind, n in counts.items()
        if n
    ]
    notice_box = Table([[Paragraph(_text(NOTICE), NOTICE_BOX)]])
    notice_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SHADE),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [
        Spacer(1, 30 * mm),
        Paragraph("Dispute dossier", TITLE),
        _para(f"Built on {_sast(built_at)}", BODY),
        _para("Prepared with Tokelo", SMALL),
        Spacer(1, 10 * mm),
        notice_box,
        Spacer(1, 8 * mm),
        Paragraph("What is in it", SUBHEADING),
        _para(
            f"{len(records)} records, chosen by the tenant: {_joined(listed)}. The index on the "
            "next page gives every part and every record with its page."
        ),
        _para(
            "Tokelo wrote the pages numbered at the foot. The lease's and the notices' own pages "
            "are copied in as they are, unnumbered, and counted in the numbering. Links, form "
            "fields, scripts and attached files were removed from them; nothing they show was "
            "changed."
        ),
        Paragraph("Checking a file against its digest", SUBHEADING),
        _para(
            "Part 8 lists every file with its SHA-256 digest, which Tokelo took from the stored "
            "file when it was uploaded. To check that a copy of a file is the same file, compute "
            "its digest and compare the two, character for character:"
        ),
        _para("On Linux: sha256sum <file>", CELL),
        _para("On macOS: shasum -a 256 <file>", CELL),
        _para("On Windows: certutil -hashfile <file> SHA256", CELL),
        Spacer(1, 3 * mm),
        _para(
            "The photographs in part 5 are shown at a reduced size. Their digests are of the "
            "originals, which Tokelo keeps."
        ),
        Spacer(1, 10 * mm),
        _para(f"Dossier {dossier_id}", SMALL),
    ]


def _index(
    pages: dict[str, int],
    present: set[str],
    in_part: dict[str, list[str]],
    dry_run: bool,
) -> list[Flowable]:
    """Every part and every record with its page. On the dry run the numbers aren't known yet,
    and a same-width stand-in takes their place, so the index takes the same room both times."""

    def number(name: str) -> str:
        return "0000" if dry_run else str(pages[name])

    rows: list[list[Paragraph]] = []
    for part in PARTS:
        if part in present or part in ("1. Cover", "2. Index"):
            rows.append([Paragraph(_text(part), CELL), Paragraph(number(part), CELL)])
            for name in in_part.get(part, []):
                rows.append(
                    [
                        Paragraph(_text(name), INDENTED),
                        Paragraph(number(name), CELL),
                    ]
                )
        else:
            # Part 7 is there whenever a lease is, so it is only ever missing for want of one.
            why = "no lease selected" if part == "7. The law cited" else "none selected"
            rows.append([Paragraph(_text(f"{part} — {why}"), CELL_MUTED), Paragraph("", CELL)])
    table = LongTable(rows, colWidths=[FRAME_WIDTH - 20 * mm, 20 * mm], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [Paragraph("2. Index", HEADING), table]


def _timeline(entries: Sequence[TimelineEntry], names: dict[str, str]) -> list[Flowable]:
    story: list[Flowable] = [
        Paragraph("3. Timeline", HEADING),
        _para(
            "Every dated entry of the chosen records, in the order it happened, in South African "
            "time (SAST, UTC+2). Beside each date is where it came from. An entry dated by its "
            "upload says so: that is when Tokelo received the file, not when anything in it "
            "happened."
        ),
    ]
    if not entries:
        story.append(_para("None of the chosen records carries a date of its own."))
        return story
    # One small table per entry rather than one long one: ReportLab splits a long table by
    # rebuilding what is left of it at every page, which made a 5 MB export's 43,000 entries
    # take minutes and more than a gigabyte. A row on its own is never split. The headings are
    # repeated at the top of every later page by the page itself (`_running_headings`).
    story.append(_row([Paragraph(f"<b>{h}</b>", CELL) for h in TIMELINE_HEADINGS], heading=True))
    for entry in entries:
        what = "Notice" if entry.source is TimelineSource.NOTICE else entry.summary
        dated_by = (
            NOTICE_DATED_BY.get(entry.summary, entry.summary)
            if entry.source is TimelineSource.NOTICE
            else DATED_BY[entry.source]
        )
        story.append(
            _row(
                [
                    Paragraph(_sast(entry.occurred_at).removesuffix(" SAST"), CELL),
                    Paragraph(_text(names.get(entry.document_id, "")), CELL),
                    Paragraph(_text(what), CELL),
                    Paragraph(_text(dated_by), CELL_MUTED),
                ]
            )
        )
    return story


TIMELINE_HEADINGS = ("When (SAST)", "Record", "What", "Date from")
_FIXED = [32 * mm, 33 * mm]
TIMELINE_WIDTHS = [
    *_FIXED,
    (FRAME_WIDTH - sum(_FIXED)) * 0.62,
    (FRAME_WIDTH - sum(_FIXED)) * 0.38,
]
ROW_PADDING = 3
HEADINGS_ROOM = 16  # points kept at the top of every timeline page for the running headings


def _row(cells: list[Paragraph], heading: bool = False) -> Table:
    row = Table([cells], colWidths=TIMELINE_WIDTHS)
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "LINEBELOW",
                    (0, 0),
                    (-1, -1),
                    0.75 if heading else 0.25,
                    INK if heading else RULE,
                ),
                ("TOPPADDING", (0, 0), (-1, -1), ROW_PADDING),
                ("BOTTOMPADDING", (0, 0), (-1, -1), ROW_PADDING),
            ]
        )
    )
    return row


def _running_headings(canvas: Canvas) -> None:
    """The timeline's column headings at the top of a page it runs on to, where they sit in the
    room the page keeps for them."""
    top = PAGE[1] - MARGIN_TOP - 10
    canvas.saveState()
    canvas.setFont("Vera-Bold", 8)
    canvas.setFillColor(INK)
    x = MARGIN_X + 6  # a cell's own left padding
    for heading, width in zip(TIMELINE_HEADINGS, TIMELINE_WIDTHS, strict=True):
        canvas.drawString(x, top, heading)
        x += width
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(0.75)
    canvas.line(MARGIN_X, top - 4, PAGE[0] - MARGIN_X, top - 4)
    canvas.restoreState()


def _document_segments(
    part: str,
    record: Record,
    names: dict[str, str],
    entries_of: dict[str, list[TimelineEntry]],
) -> list[_Segment]:
    """A record's pages in its part. A PDF: a page that introduces it, then its own pages. A
    picture: one page with its details above it. A chat export: its messages."""
    name = names[record.document.id]
    heading: list[Flowable] = [Paragraph(_text(part), SMALL), Paragraph(_text(name), HEADING)]
    details = _details(record, entries_of.get(record.document.id, []))

    kind = record.document.kind
    if kind is DocumentKind.CHAT:
        return [_Segment(part, name, make=lambda: [*heading, *details, *_messages(record)])]
    if record.pdf is not None:
        try:
            pages = sanitize.count(record.pdf)
        except sanitize.Unreadable as reason:
            said = (
                f"This PDF couldn't be opened ({reason}), so its pages aren't in this dossier. "
                "The file is still in Tokelo, and its digest is above."
            )
            return [_Segment(part, name, make=lambda: [*heading, *details, _para(said, WARNING)])]
        whose = "lease's" if kind is DocumentKind.LEASE else "notice's"
        own = (
            f"The {whose} own page follows, copied as it is. Links, form fields, scripts and "
            "attached files were removed; nothing the page shows was changed."
            if pages == 1
            else f"The {whose} own {pages} pages follow, copied as they are. Links, form fields, "
            "scripts and attached files were removed; nothing the pages show was changed."
        )
        follows = _para(own)
        return [
            _Segment(part, name, make=lambda: [*heading, *details, follows]),
            _Segment(part, None, pdf=record.pdf),
        ]
    return [_Segment(part, name, make=lambda: [*heading, *details, *_shown(record.picture)])]


def _details(record: Record, entries: Sequence[TimelineEntry]) -> list[Flowable]:
    """What Tokelo recorded about the file: for a photo, what it says about itself (REQ-009); for
    a notice, the date it is placed at and why; and for every file, when it was stored and its
    digest. A file that no longer matches that digest says so, in red, first."""
    document = record.document
    lines: list[Flowable] = []
    if not record.matches:
        lines.append(_para(MISMATCH, WARNING))
    if document.kind is DocumentKind.PHOTO:
        capture = document.capture
        when = capture.captured_at if capture else None
        located = capture is not None and None not in (capture.latitude, capture.longitude)
        place = f"{capture.latitude}, {capture.longitude}" if located and capture else None
        for label, value in (
            ("Captured", _sast(when) if when else None),
            ("Device", capture.device if capture else None),
            ("Location", place),
        ):
            lines.append(_para(f"{label}: {value or NOT_RECORDED}", CELL))
    if document.kind is DocumentKind.NOTICE:
        for entry in entries[:1]:
            dated_by = NOTICE_DATED_BY.get(entry.summary, entry.summary)
            lines.append(_para(f"Dated: {_sast(entry.occurred_at)}. {dated_by}.", CELL))
    lines.append(_para(f"Stored: {_sast(document.stored_at or document.requested_at)}", CELL))
    lines.append(_para(f"SHA-256: {document.sha256 or NOT_RECORDED}", CELL))
    lines.append(Spacer(1, 4 * mm))
    return lines


def _shown(shown: Picture | None) -> list[Flowable]:
    if shown is None:
        return [
            _para(
                "This file couldn't be shown as a picture. It is still in Tokelo, unchanged, "
                "and its digest is above.",
                WARNING,
            )
        ]
    # Fitted to the box whichever way round it is: brought down to 150 dpi by `picture`, and
    # drawn to fill the box, so a small photo is shown large rather than as a stamp.
    scale = min(PHOTO_BOX[0] / shown.width, PHOTO_BOX[1] / shown.height)
    return [Drawn(io.BytesIO(shown.jpeg), width=shown.width * scale, height=shown.height * scale)]


def _messages(record: Record) -> list[Flowable]:
    """The export's messages, whole, in time order. A message's time is the export's own,
    and messages in the same minute keep the export's order."""
    messages = sorted(record.messages, key=lambda m: m.at)  # stable: the export's own order
    if not messages:
        return [_para("This export holds no message.")]
    story: list[Flowable] = [
        _para(
            f"{len(messages)} message{'s' if len(messages) != 1 else ''}, from "
            f"{_sast(messages[0].at)} to {_sast(messages[-1].at)}. The times are the export's "
            "own, read as SAST: WhatsApp writes no time zone."
        ),
        Spacer(1, 2 * mm),
    ]
    for message in messages:
        when = _sast(message.at).removesuffix(" SAST")
        story.append(
            Paragraph(
                f"<b>{when} · {_text(message.sender)}</b><br/>{_text(message.text)}",
                MESSAGE,
            )
        )
    return story


def _flags(record: Record, names: dict[str, str]) -> list[Flowable]:
    """dossier.md §6, part 4: the lease's flagged clauses, each with the explanation and the
    sections it was shown with. A clause nothing matched isn't listed: the lease's own pages,
    just before, hold every clause (REQ-007: "no issue found by these checks")."""
    name = names[record.document.id]
    story: list[Flowable] = [
        Paragraph("4. The lease", SMALL),
        Paragraph(_text(f"{name}: flagged clauses"), HEADING),
        _para(
            "Each clause below matched one of Tokelo's checks. The explanation and the sections "
            "are the ones Tokelo showed when the lease was checked."
        ),
    ]
    if record.unreadable_pages:
        pages = _joined([str(n) for n in record.unreadable_pages])
        plural = "s" if len(record.unreadable_pages) != 1 else ""
        story.append(
            _para(
                f"Tokelo couldn't read page{plural} {pages} of this lease, so no clause on "
                f"{'them' if plural else 'it'} was checked.",
                WARNING,
            )
        )
    flagged = [c for c in sorted(record.clauses, key=lambda c: c.ordinal) if c.flags]
    if not flagged:
        story.append(_para("No issue found by these checks in any clause of this lease."))
        return story
    for clause in flagged:
        block: list[Flowable] = [
            Paragraph(_text(f"Clause {clause.label} · page {clause.first_page}"), SUBHEADING),
            _para(clause.text, QUOTE),
        ]
        for flag in clause.flags:
            block.append(_para(str(flag.get("explanation", ""))))
            rests_on = "; ".join(
                f"{s['act']}, section {s['section']}: {s['title']} ({s['id']})"
                for s in flag.get("sections", [])
            )
            block.append(_para(f"Rests on: {rests_on}", SMALL))
        # A clause that fits on a page stays on one; a longer one simply runs on, since a block
        # kept together that is taller than a page can't be laid out at all.
        if len(clause.text) < 1200:
            story.append(KeepTogether(block))
        else:
            story.extend(block)
    return story


def _law(cited: Sequence[str]) -> list[Flowable]:
    """dossier.md §6, part 7: each section the flags cite, as curated (REQ-006): its words
    reproduced line for line, never paraphrased, with where and when they were taken from."""
    story: list[Flowable] = [
        Paragraph("7. The law cited", HEADING),
        _para(
            "The sections the lease's flags rest on, in their own words, from Tokelo's curated "
            "sources. Each says where its text was taken from, and as at what date."
        ),
    ]
    if not cited:
        story.append(_para("No flag in the chosen leases cites a section."))
        return story
    for section_id in cited:
        try:
            section = sources.section(section_id)
        except sources.NotCurated:
            story.append(Paragraph(_text(section_id), SUBHEADING))
            story.append(
                _para(
                    "This section is no longer in Tokelo's curated sources, so its text isn't "
                    "reproduced here.",
                    WARNING,
                )
            )
            continue
        source = section.source
        story += [
            Paragraph(
                _text(f"{section.act}, section {section.number}: {section.title}"), SUBHEADING
            ),
            _para(
                f"{section.id} · Source: {source.publisher}, {source.url}. Retrieved "
                f"{source.retrieved}, as at {source.as_at}. {source.amendments}",
                SMALL,
            ),
            Preformatted(section.text, _fitted(section.text)),
        ]
    return story


def _fitted(text: str) -> ParagraphStyle:
    """A size at which the section's longest line fits the page: the lines are the gazette's own
    breaks and indents, kept as they are, so they may not be reflowed to fit."""
    widest = max((pdfmetrics.stringWidth(line, "Vera", 1) for line in text.splitlines()), default=1)
    size = min(8.0, FRAME_WIDTH / widest)
    return _style("law", size, size * 1.35, spaceAfter=6)


def _integrity(records: Sequence[Record], names: dict[str, str]) -> list[Flowable]:
    """dossier.md §6, part 8: every file, as Tokelo stored it."""
    story: list[Flowable] = [
        Paragraph("8. Integrity", HEADING),
        _para(
            "Every file in this dossier, as Tokelo stored it. Its SHA-256 digest was taken from "
            "the stored file when it was uploaded, and a copy with the same digest is the same "
            "file (see the cover for how to check)."
        ),
    ]
    rows: list[list[Flowable | list[Flowable]]] = [
        [Paragraph("<b>Record</b>", CELL), Paragraph("<b>The file</b>", CELL)]
    ]
    in_parts = sorted(
        records,
        key=lambda r: list(KIND_NAMES).index(r.document.kind),
    )
    for record in in_parts:
        document = record.document
        about: list[Flowable] = []
        if not record.matches:
            about.append(Paragraph(_text(MISMATCH), CELL_RED))
        about += [
            Paragraph(_text(f"SHA-256: {document.sha256 or NOT_RECORDED}"), CELL),
            Paragraph(
                _text(
                    f"{document.content_type}, {_size(document.size_bytes)}. Stored "
                    f"{_sast(document.stored_at or document.requested_at)}."
                ),
                CELL_MUTED,
            ),
            Paragraph(_text(f"Tokelo ID: {document.id}"), CELL_MUTED),
        ]
        rows.append([Paragraph(_text(names[document.id]), CELL), about])
    table = LongTable(rows, colWidths=[33 * mm, FRAME_WIDTH - 33 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    return story


def _lowered(name: str) -> str:
    """'Photo' to 'photo', in a sentence; a name that is a name stays as it is."""
    return name if name.startswith("WhatsApp") else name.lower()


def _joined(items: Sequence[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"
