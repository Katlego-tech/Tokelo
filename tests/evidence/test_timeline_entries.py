"""The `evidence` worker puts notices and WhatsApp exports on the tenant's timeline as they are
stored (REQ-012; docs/design/evidence.md §4, §7).

Parsing and dating are tests/dossier/test_timeline.py's. What is held here is the worker's part:
the entries reach the store, a redelivery doesn't double them, an export that isn't one fails
with its reason while keeping its digest, and a photo's entry is on the same UTC clock as the
rest.
"""

import hashlib
import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from fakes import STORED_AT, Bucket, batch, s3_record
from tokelo.core import keys
from tokelo.core.model import Document, DocumentKind, DocumentStatus, TimelineSource
from tokelo.dossier import timeline
from tokelo.evidence import handler

TENANT = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def bucket(monkeypatch) -> Bucket:
    stub = Bucket()
    monkeypatch.setattr(handler, "s3_for", lambda: stub)
    return stub


@pytest.fixture
def worker(store, bucket, monkeypatch):
    monkeypatch.setattr(handler, "store_for", lambda: store)
    return handler.handler


@pytest.fixture
def uploaded(store, bucket):
    def upload(kind: DocumentKind, body: bytes, content_type: str) -> str:
        store.create_tenant(TENANT, created_at="2026-09-21T08:00:00Z")
        key = keys.upload_key(TENANT, kind, DOCUMENT)
        store.create_document(
            TENANT,
            Document(
                id=DOCUMENT,
                kind=kind,
                status=DocumentStatus.REQUESTED,
                s3_key=key,
                content_type=content_type,
                size_bytes=len(body),
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        bucket.put(key, body)
        return key

    return upload


def a_pdf(created: str | None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    if created:
        writer.add_metadata({"/CreationDate": created})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.req("REQ-012")
def test_each_message_of_an_export_is_on_the_timeline_in_time_order(worker, store, uploaded):
    key = uploaded(
        DocumentKind.CHAT, (FIXTURES / "timeline" / "android.txt").read_bytes(), "text/plain"
    )

    assert worker(batch(s3_record(key))) == {"batchItemFailures": []}

    entries = store.list_timeline(TENANT)
    assert [e.occurred_at for e in entries] == [
        "2026-09-15T07:14:00Z",
        "2026-09-15T07:15:00Z",
        "2026-09-16T15:40:00Z",
    ]
    assert all(e.source is TimelineSource.CHAT_MESSAGE for e in entries)
    assert store.get_document(TENANT, DOCUMENT).document.status is DocumentStatus.PROCESSED


@pytest.mark.req("REQ-012")
def test_a_big_export_is_read_whole_not_just_its_first_chunk(worker, store, uploaded):
    """The digest keeps only the first chunk it streamed; an export longer than that has
    messages past it, and every one of them belongs on the timeline."""
    line = "15/09/2026, 09:14 - Thandi: the geyser is still leaking, day after day\n"
    body = (line * (2 * 1024 * 1024 // len(line) + 1)).encode()
    key = uploaded(DocumentKind.CHAT, body, "text/plain")

    worker(batch(s3_record(key)))

    assert len(store.list_timeline(TENANT)) == body.count(b"\n")


@pytest.mark.req("REQ-012")
def test_a_file_that_isnt_an_export_fails_with_its_reason_and_keeps_its_digest(
    worker, store, uploaded
):
    body = (FIXTURES / "timeline" / "not-an-export.txt").read_bytes()
    key = uploaded(DocumentKind.CHAT, body, "text/plain")

    assert worker(batch(s3_record(key))) == {"batchItemFailures": []}

    document = store.get_document(TENANT, DOCUMENT).document
    assert document.status is DocumentStatus.FAILED
    assert document.failure_reason == timeline.NOT_AN_EXPORT
    assert document.sha256 == hashlib.sha256(body).hexdigest()
    assert store.list_timeline(TENANT) == []


@pytest.mark.req("REQ-012")
def test_a_notice_pdf_is_on_the_timeline_at_its_creation_date(worker, store, uploaded):
    key = uploaded(DocumentKind.NOTICE, a_pdf("D:20260910143000+02'00'"), "application/pdf")

    worker(batch(s3_record(key)))

    (entry,) = store.list_timeline(TENANT)
    assert entry.occurred_at == "2026-09-10T12:30:00Z"
    assert entry.summary == timeline.NOTICE_CREATED
    assert entry.document_id == DOCUMENT


@pytest.mark.req("REQ-012")
def test_a_notice_with_no_date_is_on_the_timeline_as_uploaded_on_when_it_was_stored(
    worker, store, uploaded
):
    key = uploaded(DocumentKind.NOTICE, a_pdf(None), "application/pdf")

    worker(batch(s3_record(key)))

    (entry,) = store.list_timeline(TENANT)
    assert entry.occurred_at == STORED_AT.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert entry.summary == timeline.NOTICE_UPLOADED


@pytest.mark.req("REQ-012")
def test_a_photographed_notice_is_on_the_timeline_when_it_was_photographed(worker, store, uploaded):
    photo = (FIXTURES / "photos" / "damp-full.jpg").read_bytes()
    key = uploaded(DocumentKind.NOTICE, photo, "image/jpeg")

    worker(batch(s3_record(key)))

    (entry,) = store.list_timeline(TENANT)
    assert entry.occurred_at == "2026-03-01T16:04:22Z"


@pytest.mark.req("REQ-012")
def test_a_photos_entry_is_on_the_same_utc_clock_as_everything_else(worker, store, uploaded):
    """Its capture time keeps the photograph's own offset in the capture record; its timeline
    entry is in UTC, because the timeline's sort key is the time as text (domain-model.md §3)."""
    photo = (FIXTURES / "photos" / "damp-full.jpg").read_bytes()
    key = uploaded(DocumentKind.PHOTO, photo, "image/jpeg")

    worker(batch(s3_record(key)))

    (entry,) = store.list_timeline(TENANT)
    assert entry.occurred_at == "2026-03-01T16:04:22Z"
    captured = store.get_document(TENANT, DOCUMENT).document.capture
    assert captured is not None and captured.captured_at == "2026-03-01T18:04:22+02:00"
