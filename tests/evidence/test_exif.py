"""What a photograph says about itself (REQ-009; docs/design/evidence.md §6, §9).

REQ-009 is two promises, and the second is the harder one: record the capture time, the device
and the GPS **where present**, and say "not recorded" where absent. Nothing is inferred — above
all, the time the file was uploaded is never used as the time the photograph was taken. A tenant
standing at a Tribunal with a date Tokelo invented would be worse off than one with no date.

So every test here is either "this was read correctly" or "this was left alone".
"""

import io
from pathlib import Path

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from fakes import Bucket, batch, s3_record
from tokelo.core import keys
from tokelo.core.model import Document, DocumentKind, DocumentStatus, TimelineSource
from tokelo.evidence import exif, handler

PHOTOS = Path(__file__).resolve().parents[1] / "fixtures" / "photos"

TENANT = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
PHOTO_KEY = keys.upload_key(TENANT, DocumentKind.PHOTO, DOCUMENT)

MAKE, MODEL = 0x010F, 0x0110
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATE_TIME_ORIGINAL, OFFSET_TIME_ORIGINAL = 0x9003, 0x9011


def photo(name: str) -> bytes:
    return (PHOTOS / name).read_bytes()


def a_photo_with(
    *,
    taken: str | None = "2026:03:01 18:04:22",
    offset: str | None = None,
    make: str | None = None,
    model: str | None = None,
    gps: tuple[str, float, str, float] | None = None,
) -> bytes:
    """A JPEG with exactly the EXIF a case needs, for the ones no shipped fixture should carry."""
    image = Image.new("RGB", (32, 32), (200, 190, 180))
    tags = image.getexif()
    if make:
        tags[MAKE] = make
    if model:
        tags[MODEL] = model
    if taken:
        tags.get_ifd(EXIF_IFD)[DATE_TIME_ORIGINAL] = taken
    if offset:
        tags.get_ifd(EXIF_IFD)[OFFSET_TIME_ORIGINAL] = offset
    if gps:
        lat_ref, lat, lon_ref, lon = gps
        where = tags.get_ifd(GPS_IFD)
        where[1], where[3] = lat_ref, lon_ref
        where[2] = (IFDRational(int(lat), 1), IFDRational(0, 1), IFDRational(0, 1))
        where[4] = (IFDRational(int(lon), 1), IFDRational(0, 1), IFDRational(0, 1))

    out = io.BytesIO()
    image.save(out, format="JPEG", exif=tags)
    return out.getvalue()


@pytest.mark.req("REQ-009")
def test_a_photo_that_carries_everything_is_read_in_full():
    """A phone with location on. All four fields, and the coordinates as decimal degrees."""
    capture = exif.of(photo("damp-full.jpg"))

    assert capture.captured_at == "2026-03-01T18:04:22+02:00"
    assert capture.device == "Samsung SM-A536B"
    assert capture.latitude == pytest.approx(-25.742)
    assert capture.longitude == pytest.approx(28.188)


@pytest.mark.req("REQ-009")
def test_south_and_west_are_negative():
    """The hemisphere is a separate tag from the number, and a reader that ignores it puts a
    Pretoria flat in Egypt. 14B Marabastad Road is south and east."""
    capture = exif.of(photo("damp-full.jpg"))
    assert capture.latitude is not None and capture.latitude < 0, "Pretoria is south"
    assert capture.longitude is not None and capture.longitude > 0, "Pretoria is east"

    north_west = exif.of(a_photo_with(gps=("N", 51, "W", 0)))
    assert north_west.latitude == pytest.approx(51.0)
    assert north_west.longitude == pytest.approx(-0.0)


@pytest.mark.req("REQ-009")
def test_a_photo_with_location_off_keeps_its_time_and_has_no_coordinates():
    """The common case. Nothing is put in the gap: a missing coordinate stays missing."""
    capture = exif.of(photo("damp-no-gps.jpg"))

    assert capture.captured_at == "2026-03-01T18:04:22+02:00"
    assert capture.device == "Samsung SM-A536B"
    assert capture.latitude is None
    assert capture.longitude is None


@pytest.mark.req("REQ-009")
def test_a_time_with_no_offset_is_read_as_south_african_time_and_says_so():
    """evidence.md §6: EXIF's DateTimeOriginal has no zone. Tokelo is for South African tenants,
    so it is read as SAST — and the offset is kept in what is stored, so nobody later has to
    guess which zone an hour was meant in."""
    captured_at = exif.of(photo("damp-no-gps.jpg")).captured_at
    assert captured_at is not None and captured_at.endswith("+02:00")


@pytest.mark.req("REQ-009")
def test_an_offset_the_photo_carries_is_used_rather_than_assumed():
    """A phone that recorded its own zone is believed over the default."""
    capture = exif.of(a_photo_with(offset="+01:00"))
    assert capture.captured_at == "2026-03-01T18:04:22+01:00"


@pytest.mark.req("REQ-009")
def test_a_photo_with_no_exif_at_all_records_nothing():
    """A screenshot, or a photo put through an app that strips it. Not a failure — just nothing
    to record, which the view shows as "not recorded"."""
    capture = exif.of(photo("damp-bare.jpg"))

    assert capture.captured_at is None
    assert capture.device is None
    assert capture.latitude is None and capture.longitude is None


@pytest.mark.req("REQ-009")
@pytest.mark.parametrize(
    "data",
    [b"", b"not a photograph at all", b"\xff\xd8\xff\xe0" + b"\x00" * 64],
    ids=["empty", "not an image", "a truncated JPEG"],
)
def test_something_that_cannot_be_read_records_nothing_rather_than_failing(data):
    """evidence.md §4: "EXIF can't be read, or isn't there: the capture fields stay NULL. That
    isn't a failure." The file is still evidence — its digest is what matters."""
    assert exif.of(data) == exif.Capture()


@pytest.mark.req("REQ-009")
def test_a_device_is_whichever_halves_the_photo_has():
    """Make and Model are two tags, and phones fill them in inconsistently."""
    assert exif.of(a_photo_with(make="Apple", model="iPhone 13")).device == "Apple iPhone 13"
    assert exif.of(a_photo_with(make="Nokia")).device == "Nokia"
    assert exif.of(a_photo_with(model="SM-A536B")).device == "SM-A536B"
    assert exif.of(a_photo_with()).device is None
    # Some phones repeat the make inside the model; saying it twice reads like a bug.
    assert exif.of(a_photo_with(make="Samsung", model="Samsung SM-A536B")).device == (
        "Samsung SM-A536B"
    )


@pytest.mark.req("REQ-009")
def test_a_time_that_is_not_a_time_is_not_recorded():
    """A field that is there but unreadable is the same as one that isn't: nothing."""
    assert exif.of(a_photo_with(taken="not a date")).captured_at is None
    assert exif.of(a_photo_with(taken="0000:00:00 00:00:00")).captured_at is None


# ------------------------------------------------- what the worker does with it ---
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
    def upload(name: str = "damp-full.jpg") -> bytes:
        body = photo(name)
        store.create_tenant(TENANT, created_at="2026-09-21T08:00:00Z")
        store.create_document(
            TENANT,
            Document(
                id=DOCUMENT,
                kind=DocumentKind.PHOTO,
                status=DocumentStatus.REQUESTED,
                s3_key=PHOTO_KEY,
                content_type="image/jpeg",
                size_bytes=len(body),
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        bucket.put(PHOTO_KEY, body)
        return body

    return upload


@pytest.mark.req("REQ-009")
def test_the_worker_stores_what_the_photo_carried(worker, store, uploaded):
    """T038's Done: stored with the file's record."""
    uploaded()

    assert worker(batch(s3_record(PHOTO_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None and stored.document.capture is not None
    assert stored.document.status is DocumentStatus.PROCESSED
    assert stored.document.capture.captured_at == "2026-03-01T18:04:22+02:00"
    assert stored.document.capture.device == "Samsung SM-A536B"
    assert stored.document.capture.latitude == pytest.approx(-25.742)


@pytest.mark.req("REQ-012")
def test_a_photo_that_knows_when_it_was_taken_lands_on_the_timeline_at_that_time(
    worker, store, uploaded
):
    """evidence.md §4. The entry is dated by the photograph, not by the upload — which is the
    whole reason a tenant photographs the damp the day it appears."""
    uploaded()

    assert worker(batch(s3_record(PHOTO_KEY))) == {"batchItemFailures": []}

    entries = store.list_timeline(TENANT)
    assert len(entries) == 1
    assert entries[0].source is TimelineSource.CAPTURE
    assert entries[0].occurred_at.startswith("2026-03-01T")
    assert entries[0].document_id == DOCUMENT


@pytest.mark.req("REQ-009")
def test_a_photo_with_no_time_gets_no_timeline_entry(worker, store, uploaded):
    """Nothing is invented. A photo with no capture time has no place on a timeline, and the
    upload time is not a stand-in for one (REQ-009)."""
    uploaded("damp-bare.jpg")

    assert worker(batch(s3_record(PHOTO_KEY))) == {"batchItemFailures": []}

    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.capture is None or stored.document.capture.captured_at is None
    assert store.list_timeline(TENANT) == []


@pytest.mark.req("REQ-009")
def test_a_second_delivery_leaves_one_timeline_entry(worker, store, uploaded):
    """ADR-0007. A redelivered photo must not appear on the tenant's timeline twice."""
    uploaded()

    worker(batch(s3_record(PHOTO_KEY)))
    worker(batch(s3_record(PHOTO_KEY, message_id="m2", receives=2)))

    assert len(store.list_timeline(TENANT)) == 1


def test_the_fixtures_are_what_they_say_they_are():
    """Not about the reader: about the photographs. If they drift, every test above is theatre."""
    assert (PHOTOS / "build.py").exists()
    full = Image.open(io.BytesIO(photo("damp-full.jpg"))).getexif()
    assert full.get(MAKE) == "Samsung"
    assert dict(full.get_ifd(GPS_IFD)), "damp-full.jpg is the one with GPS"
    assert not dict(Image.open(io.BytesIO(photo("damp-bare.jpg"))).getexif()), "bare means bare"
