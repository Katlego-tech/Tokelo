"""The timeline: WhatsApp exports and notices as dated entries, and the order they're shown in
(REQ-012; docs/design/evidence.md §6, docs/design/dossier.md §6 "Ordering the timeline").

A timeline is worth putting in front of a Tribunal only if every date on it came off the evidence
and says where it came from. So what is held here is mostly about dates: SAST read correctly into
UTC, nothing guessed, and an upload time never passed off as when something happened.

The exports are synthetic (tests/fixtures/timeline/): real tenants' chats never enter the
repository.
"""

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from tokelo.core.model import TimelineEntry, TimelineSource
from tokelo.dossier import timeline
from tokelo.dossier.timeline import NotAnExport

FIXTURES = Path(__file__).parent.parent / "fixtures"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
LATER = "44444444-4444-4444-8444-444444444444"
UPLOADED = "2026-09-20T08:30:00Z"


def export(name: str) -> bytes:
    return (FIXTURES / "timeline" / name).read_bytes()


def a_pdf(created: str | None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    if created:
        writer.add_metadata({"/CreationDate": created})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ------------------------------------------------------------------ WhatsApp ---
@pytest.mark.req("REQ-012")
def test_an_android_export_becomes_one_message_per_sender_line():
    messages = timeline.messages(export("android.txt").decode())

    assert [(m.at, m.sender) for m in messages] == [
        # 09:14 in SAST is 07:14 UTC: an export has no zone, and Tokelo reads it as SAST.
        ("2026-09-15T07:14:00Z", "Thandi"),
        ("2026-09-15T07:15:00Z", "Thandi"),
        ("2026-09-16T15:40:00Z", "Mr Botha"),
    ]


@pytest.mark.req("REQ-012")
def test_a_line_in_neither_format_belongs_to_the_message_before_it():
    """As WhatsApp writes a multi-line message. A line with an impossible date is not a new
    message either; and the encryption notice, before any message, has nothing to join."""
    second = timeline.messages(export("android.txt").decode())[1]

    assert second.text == (
        "The water is coming through the ceiling\n"
        "into the main bedroom.\n"
        "31/02/2026, 10:00 - this line has an impossible date, so it belongs to the message above"
    )


@pytest.mark.req("REQ-012")
def test_an_ios_export_reads_its_seconds_and_ignores_its_direction_marks():
    messages = timeline.messages(export("ios.txt").decode())

    assert [(m.at, m.sender, m.text) for m in messages] == [
        (
            "2026-09-15T07:14:05Z",
            "Thandi",
            "Good morning, the geyser has been leaking since Saturday.",
        ),
        ("2026-09-15T07:15:30Z", "Thandi", "image omitted"),
        ("2026-09-16T15:40:12Z", "Mr Botha", "I will send someone next week."),
    ]


@pytest.mark.req("REQ-012")
def test_a_file_with_no_line_in_either_format_is_not_an_export():
    with pytest.raises(NotAnExport):
        timeline.chat_entries(DOCUMENT, export("not-an-export.txt"))


@pytest.mark.req("REQ-012")
def test_each_message_is_one_entry_with_its_sender_in_the_summary():
    entries = timeline.chat_entries(DOCUMENT, export("ios.txt"))

    assert len(entries) == 3
    assert all(e.source is TimelineSource.CHAT_MESSAGE for e in entries)
    assert all(e.document_id == DOCUMENT for e in entries)
    assert entries[2].summary == "Mr Botha: I will send someone next week."
    # The same export always makes the same entries, so a redelivery rewrites rather than adds.
    assert [e.id for e in entries] == [
        e.id for e in timeline.chat_entries(DOCUMENT, export("ios.txt"))
    ]
    assert len({e.id for e in entries}) == 3


@pytest.mark.req("REQ-012")
def test_a_long_message_is_cut_to_500_characters():
    text = "15/09/2026, 09:14 - Thandi: " + "drip " * 300

    (entry,) = timeline.chat_entries(DOCUMENT, text.encode())

    assert len(entry.summary) == 500
    assert entry.summary.startswith("Thandi: drip")


@pytest.mark.req("REQ-012")
def test_an_export_saved_with_a_byte_order_mark_still_reads():
    (entry, *_) = timeline.chat_entries(DOCUMENT, b"\xef\xbb\xbf" + export("android.txt"))

    assert entry.summary.startswith("Thandi: Good morning")


# -------------------------------------------------------------------- notices ---
@pytest.mark.req("REQ-012")
def test_a_photographed_notice_is_dated_by_when_it_was_photographed():
    photo = (FIXTURES / "photos" / "damp-full.jpg").read_bytes()

    entry = timeline.notice_entry(DOCUMENT, "image/jpeg", photo, UPLOADED)

    # 18:04:22 at +02:00, as the photograph recorded it.
    assert entry.occurred_at == "2026-03-01T16:04:22Z"
    assert entry.summary == timeline.NOTICE_PHOTOGRAPHED
    assert entry.source is TimelineSource.NOTICE


@pytest.mark.req("REQ-012")
def test_a_notice_pdf_is_dated_by_its_creation_date():
    entry = timeline.notice_entry(
        DOCUMENT, "application/pdf", a_pdf("D:20260910143000+02'00'"), UPLOADED
    )

    assert entry.occurred_at == "2026-09-10T12:30:00Z"
    assert entry.summary == timeline.NOTICE_CREATED


@pytest.mark.req("REQ-012")
def test_a_creation_date_with_no_zone_is_read_as_sast():
    entry = timeline.notice_entry(DOCUMENT, "application/pdf", a_pdf("D:20260910143000"), UPLOADED)

    assert entry.occurred_at == "2026-09-10T12:30:00Z"


@pytest.mark.req("REQ-012")
@pytest.mark.parametrize(
    ("content_type", "data"),
    [
        ("application/pdf", a_pdf(None)),
        ("application/pdf", b"%PDF-1.7 and then nothing a reader can use"),
        ("image/jpeg", (FIXTURES / "photos" / "damp-bare.jpg").read_bytes()),
    ],
    ids=["pdf-without-a-date", "broken-pdf", "photo-without-exif"],
)
def test_a_notice_that_carries_no_date_is_labelled_as_uploaded_on(content_type, data):
    """dossier.md §6: an entry dated by its upload is labelled so, never passed off as when the
    notice was served."""
    entry = timeline.notice_entry(DOCUMENT, content_type, data, UPLOADED)

    assert entry.occurred_at == UPLOADED
    assert entry.summary == timeline.NOTICE_UPLOADED
    assert "uploaded on" in entry.summary


# ------------------------------------------------------------------ ordering ---
def entry(occurred_at: str, document_id: str, entry_id: str) -> TimelineEntry:
    return TimelineEntry(
        id=entry_id,
        occurred_at=occurred_at,
        source=TimelineSource.CHAT_MESSAGE,
        summary="",
        document_id=document_id,
    )


@pytest.mark.req("REQ-012")
def test_entries_sort_by_the_instant_whatever_zone_they_were_written_in():
    """A photo's capture time keeps its own offset; everything else is UTC. 18:00 at +02:00 is
    before 16:30 UTC, and a sort on the text alone would put it after."""
    photo = entry("2026-09-15T18:00:00+02:00", DOCUMENT, "photo")
    message = entry("2026-09-15T16:30:00Z", LATER, "message")

    assert timeline.ordered([message, photo], {}) == [photo, message]


@pytest.mark.req("REQ-012")
def test_entries_on_the_same_instant_go_by_upload_order_then_their_own_order():
    uploaded = {DOCUMENT: "2026-09-20T08:00:00Z", LATER: "2026-09-19T08:00:00Z"}
    at = "2026-09-15T07:14:00Z"
    first_uploaded = entry(at, LATER, f"{LATER}:00001")
    one = entry(at, DOCUMENT, f"{DOCUMENT}:00001")
    two = entry(at, DOCUMENT, f"{DOCUMENT}:00002")

    assert timeline.ordered([two, one, first_uploaded], uploaded) == [first_uploaded, one, two]


@pytest.mark.req("REQ-012")
def test_times_are_shown_in_sast():
    assert timeline.in_sast("2026-09-15T07:14:00Z") == "2026-09-15 09:14 SAST"
    assert timeline.in_sast("2026-03-01T18:04:22+02:00") == "2026-03-01 18:04 SAST"


@pytest.mark.req("REQ-012")
def test_one_enormous_multi_line_message_is_read_in_linear_time():
    """A 5 MB export that is one message and a hundred thousand continuation lines."""
    import time

    body = (
        "15/09/2026, 09:14 - Thandi: start\n" + "and another line of the same message\n" * 130_000
    )

    started = time.perf_counter()
    (message,) = timeline.messages(body)
    assert time.perf_counter() - started < 2

    assert message.text.count("\n") == 130_000
