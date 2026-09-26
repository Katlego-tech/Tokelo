"""The tenant's timeline: notices and WhatsApp exports as dated entries, and the order entries are
shown in (REQ-012; docs/design/evidence.md §6, docs/design/dossier.md §6).

A timeline is worth showing a Tribunal only if every date on it came off the evidence, and says
where it came from. Three rules follow, and everything here serves one of them.

**Nothing is guessed.** An export has no time zone, so its times are read as SAST, which is what a
South African phone wrote; a notice is dated by what it carries — the photograph's capture time,
then the PDF's creation date — and only then by its upload, **labelled as such**
(`NOTICE_UPLOADED`), never passed off as the day it was served.

**One clock.** Every time an entry is written with is UTC, to the second, because the store sorts
the timeline on the time as text (domain-model.md §3). A photograph's capture record keeps its own
offset; its timeline entry doesn't.

**The same file makes the same entries.** An entry's ID is its document's, with the message's
position for an export, so a redelivered job rewrites what it wrote rather than adding to it
(ADR-0007).

The `evidence` worker calls this at upload (evidence.md §7); the dossier orders what it selects
with `ordered` (T043).
"""

import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from tokelo.core.model import TimelineEntry, TimelineSource
from tokelo.evidence import exif

# South African Standard Time. There is no daylight saving, so a fixed offset is the whole of it.
SAST = timezone(timedelta(hours=2), "SAST")

# evidence.md §6: a message's summary is its sender and its text, cut to this.
SUMMARY_LIMIT = 500

# Where a notice's date came from, in the words the timeline and the dossier show (dossier.md §6).
NOTICE_PHOTOGRAPHED = "Notice, dated by when it was photographed"
NOTICE_CREATED = "Notice, dated by the PDF's creation date"
NOTICE_UPLOADED = "Notice, uploaded on this date: the file carries no date of its own"

NOT_AN_EXPORT = "This isn't a WhatsApp export: no line is in either of WhatsApp's formats."

# evidence.md §6's two formats, one per platform. The sender runs to the first ": ", which is how
# WhatsApp writes it; a line with a time but no sender (the encryption notice, "X left") matches
# neither, and so joins the message before it, as any other line would.
ANDROID = re.compile(
    r"^(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4}), (?P<hour>\d{2}):(?P<minute>\d{2})"
    r" - (?P<sender>[^:]+?): (?P<text>.*)$"
)
IOS = re.compile(
    r"^\[(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4}),"
    r" (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\] (?P<sender>[^:]+?): (?P<text>.*)$"
)

# iOS marks some lines with left-to-right marks, and a saved export may start with a byte order
# mark. Neither is part of what anyone wrote.
INVISIBLE = "‎‏﻿"


class NotAnExport(ValueError):
    """A chat upload with no line in either of WhatsApp's formats."""


@dataclass
class Message:
    at: str
    sender: str
    text: str


# ------------------------------------------------------------------ WhatsApp ---
def messages(text: str) -> list[Message]:
    """The export's messages, in the order it lists them. A line in neither format belongs to the
    message before it (a multi-line message); before the first message it belongs to nothing.

    Each message's lines are gathered in a list and joined once, so one message of a hundred
    thousand lines costs a hundred thousand appends, not a hundred thousand ever-longer copies."""
    found: list[Message] = []
    lines: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.lstrip(INVISIBLE)
        started = _message(line)
        if started is not None:
            found.append(started)
            lines.append([started.text])
        elif lines:
            lines[-1].append(line)
    for message, parts in zip(found, lines, strict=True):
        message.text = "\n".join(parts)
    return found


def _message(line: str) -> Message | None:
    match = ANDROID.match(line) or IOS.match(line)
    if match is None:
        return None
    try:
        local = datetime(
            int(match["year"]),
            int(match["month"]),
            int(match["day"]),
            int(match["hour"]),
            int(match["minute"]),
            int(match.groupdict().get("second") or 0),
            tzinfo=SAST,
        )
    except ValueError:
        return None  # 31/02, 25:00: the shape of a date, but not a date
    return Message(
        at=_stamp(local), sender=match["sender"].strip(), text=match["text"].lstrip(INVISIBLE)
    )


def chat_entries(document_id: str, data: bytes) -> list[TimelineEntry]:
    """One entry per message. Raises NotAnExport when there are none (evidence.md §4)."""
    found = messages(data.decode("utf-8-sig", errors="replace"))
    if not found:
        raise NotAnExport(NOT_AN_EXPORT)
    return [
        TimelineEntry(
            id=f"{document_id}:{n:05d}",
            occurred_at=message.at,
            source=TimelineSource.CHAT_MESSAGE,
            summary=f"{message.sender}: {message.text}"[:SUMMARY_LIMIT],
            document_id=document_id,
        )
        for n, message in enumerate(found, start=1)
    ]


# -------------------------------------------------------------------- notices ---
def notice_entry(
    document_id: str, content_type: str, data: bytes, uploaded_at: str
) -> TimelineEntry:
    """A notice's one entry, dated by evidence.md §6's order: when it was photographed, else the
    PDF's creation date, else its upload — and the summary says which.

    `data` is what holds the date: a photograph's first chunk (its EXIF is in it), or the whole
    PDF (its document information may be anywhere in it)."""
    occurred_at, summary = uploaded_at, NOTICE_UPLOADED
    if content_type.startswith("image/"):
        captured = exif.of(data).captured_at
        if captured is not None:
            occurred_at, summary = utc(captured), NOTICE_PHOTOGRAPHED
    elif content_type == "application/pdf":
        created = pdf_created(data)
        if created is not None:
            occurred_at, summary = created, NOTICE_CREATED
    return TimelineEntry(
        id=document_id,
        occurred_at=occurred_at,
        source=TimelineSource.NOTICE,
        summary=summary,
        document_id=document_id,
    )


def pdf_created(data: bytes) -> str | None:
    """The PDF's own creation date in UTC, or None when it has none or can't be read. A date with
    no zone is read as SAST, as a photograph's is (evidence.md §6)."""
    from pypdf import PdfReader

    try:
        created = PdfReader(io.BytesIO(data)).metadata
        when = created.creation_date if created is not None else None
    except Exception:
        # A notice that isn't a readable PDF still gets its entry, dated by its upload. Its
        # digest, taken already, is what makes it evidence.
        return None
    if when is None:
        return None
    return _stamp(when if when.tzinfo else when.replace(tzinfo=SAST))


# ------------------------------------------------------------------ ordering ---
def utc(text: str) -> str:
    """An ISO-8601 time with any offset, as UTC to the second."""
    return _stamp(datetime.fromisoformat(text))


def ordered(entries: Iterable[TimelineEntry], uploaded: Mapping[str, str]) -> list[TimelineEntry]:
    """dossier.md §6: by the instant, then by the document's upload order (`uploaded` maps a
    document to when it was requested), then by the entry's own order within its document."""
    return sorted(
        entries,
        key=lambda e: (utc(e.occurred_at), uploaded.get(e.document_id, ""), e.id),
    )


def in_sast(text: str) -> str:
    """A time as the timeline shows it: South African time, to the minute (dossier.md §6)."""
    return datetime.fromisoformat(text).astimezone(SAST).strftime("%Y-%m-%d %H:%M SAST")


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
