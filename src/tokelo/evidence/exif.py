"""What a photograph says about itself (REQ-009; docs/design/evidence.md §6).

One rule, and everything here follows from it: **nothing is inferred.** A field the photograph
carries is recorded; a field it doesn't carry stays absent, and the API says "not recorded". In
particular the upload time is never used as a capture time — a tenant standing at a Tribunal with
a date Tokelo invented would be worse off than one with no date at all.

Reading EXIF cannot fail the upload either. A screenshot, a photo an app has stripped, a file
that isn't really a JPEG: all of them record nothing and none of them is an error. The digest is
what makes the file evidence (REQ-008); this is what makes it easier to place.

**It reads a prefix, not the file.** EXIF lives in a JPEG's APP1 segment, right after the start
marker and capped at 64 KB by the format, so the first chunk the digest already streamed
([digest.py](digest.py)) always contains it. A 20 MB photograph is never held whole to find out
what phone took it.
"""

import io

from tokelo.core.model import Capture

# Exif 2.32's tag numbers, so the intent is readable without a table to hand.
MAKE, MODEL = 0x010F, 0x0110
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATE_TIME_ORIGINAL, OFFSET_TIME_ORIGINAL = 0x9003, 0x9011
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON = 1, 2, 3, 4

# EXIF's own format for a time, which carries no zone at all.
EXIF_TIME = "%Y:%m:%d %H:%M:%S"

# Tokelo is for South African tenants, so a photograph with no offset is read as South African
# time (evidence.md §6). The offset is kept in what is stored, so nobody later has to guess which
# zone an hour was meant in.
SAST = "+02:00"

# About 10 cm, which is far finer than a phone's GPS and stops a float's last digits being
# recorded as though they meant something.
PLACES = 6

# The hemispheres that count backwards from the number EXIF stores.
NEGATIVE = ("S", "W")


# The stored shape is the one the model already has (core/model.py): a field the photograph
# didn't carry is None there too, and the API shows it as "not recorded".
__all__ = ["Capture", "of"]


def of(data: bytes) -> Capture:
    """The capture metadata in `data`, which may be the whole photograph or its first chunk."""
    from PIL import Image

    try:
        tags = Image.open(io.BytesIO(data)).getexif()
    except Exception:
        # Not an image, or too little of one to have a header. Not a failure: nothing to record.
        return Capture()

    try:
        taken = dict(tags.get_ifd(EXIF_IFD))
        where = dict(tags.get_ifd(GPS_IFD))
    except Exception:
        taken, where = {}, {}

    return Capture(
        captured_at=when(taken.get(DATE_TIME_ORIGINAL), taken.get(OFFSET_TIME_ORIGINAL)),
        device=device(tags.get(MAKE), tags.get(MODEL)),
        latitude=degrees(where.get(GPS_LAT), where.get(GPS_LAT_REF)),
        longitude=degrees(where.get(GPS_LON), where.get(GPS_LON_REF)),
    )


def when(raw: object, offset: object) -> str | None:
    """`DateTimeOriginal`, with its offset if the photograph recorded one, else SAST.

    A field that is there but isn't a time — `0000:00:00 00:00:00` is what some phones write when
    the clock was never set — is the same as a field that isn't there: nothing.
    """
    from datetime import datetime

    text = str(raw or "").strip()
    if not text:
        return None
    try:
        at = datetime.strptime(text, EXIF_TIME)
    except ValueError:
        return None
    return at.strftime("%Y-%m-%dT%H:%M:%S") + zone(offset)


def zone(offset: object) -> str:
    """The photograph's own offset, when it wrote one this project can read."""
    text = str(offset or "").strip()
    if len(text) == 6 and text[0] in "+-" and text[3] == ":":
        if text[1:3].isdigit() and text[4:6].isdigit():
            return text
    return SAST


def device(make: object, model: object) -> str | None:
    """`Make` and `Model`, as one name. Phones fill the two in inconsistently, and some repeat
    the make inside the model — saying it twice reads like a bug."""
    first, second = str(make or "").strip(), str(model or "").strip()
    if second.lower().startswith(first.lower()) and first:
        return second
    return " ".join(part for part in (first, second) if part) or None


def degrees(dms: object, reference: object) -> float | None:
    """Degrees, minutes and seconds as EXIF stores them, in decimal degrees.

    The hemisphere is a separate tag from the number, and a reader that ignores it puts a Pretoria
    flat in Egypt.
    """
    if not isinstance(dms, tuple | list) or len(dms) != 3:
        return None
    try:
        d, m, s = (float(part) for part in dms)
    except TypeError, ValueError, ZeroDivisionError:
        return None

    decimal = round(d + m / 60 + s / 3600, PLACES)
    return -decimal if str(reference or "").strip().upper() in NEGATIVE else decimal
