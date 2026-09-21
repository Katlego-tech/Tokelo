"""Build the sample photographs (T038; docs/design/evidence.md §6).

A tenant photographs the damp patch on their bedroom ceiling. What their phone writes alongside
the pixels is what REQ-009 is about, and phones differ — so there is one of each case the reader
has to survive:

  damp-full.jpg     a phone with location on: capture time with its offset, make and model, GPS
  damp-no-gps.jpg   location off, which is the common one: a time with no offset, and no GPS
  damp-bare.jpg     no EXIF at all — a screenshot, or a photo put through an app that strips it

Nothing here is a real photograph of anything: the image is a few flat shapes, because what is
being tested is the metadata and not the picture. Everything is deterministic, so rebuilding
gives the same bytes and a failing test means the reader changed.

    uv run python tests/fixtures/photos/build.py
"""

from pathlib import Path

from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

HERE = Path(__file__).resolve().parent

# EXIF tag numbers, so the intent is readable without a table (Exif 2.32).
MAKE, MODEL = 0x010F, 0x0110
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATE_TIME_ORIGINAL, OFFSET_TIME_ORIGINAL = 0x9003, 0x9011
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON = 1, 2, 3, 4


def degrees(d: int, m: int, hundredths: int) -> tuple[IFDRational, ...]:
    """Degrees, minutes and seconds, as EXIF stores them: three rationals."""
    return (IFDRational(d, 1), IFDRational(m, 1), IFDRational(hundredths, 100))


# 14B Marabastad Road, Pretoria — the address in the sample lease, south of the equator and east
# of Greenwich, which is the pair of signs a reader gets wrong if it ignores the reference.
LATITUDE = degrees(25, 44, 3120)  # 25° 44' 31.2" S
LONGITUDE = degrees(28, 11, 1680)  # 28° 11' 16.8" E


def a_damp_ceiling() -> Image.Image:
    """Something that looks like a photograph of a stain, in as few strokes as possible."""
    image = Image.new("RGB", (640, 480), (232, 230, 224))
    draw = ImageDraw.Draw(image)
    draw.ellipse((180, 120, 470, 330), fill=(176, 158, 132))
    draw.ellipse((230, 160, 420, 290), fill=(150, 128, 98))
    draw.line((0, 96, 640, 96), fill=(205, 203, 197), width=6)
    return image


def with_exif(gps: bool, offset: bool) -> Image.Image:
    image = a_damp_ceiling()
    exif = image.getexif()
    exif[MAKE] = "Samsung"
    exif[MODEL] = "SM-A536B"

    taken = exif.get_ifd(EXIF_IFD)
    taken[DATE_TIME_ORIGINAL] = "2026:03:01 18:04:22"
    if offset:
        taken[OFFSET_TIME_ORIGINAL] = "+02:00"

    if gps:
        where = exif.get_ifd(GPS_IFD)
        where[GPS_LAT_REF] = "S"
        where[GPS_LAT] = LATITUDE
        where[GPS_LON_REF] = "E"
        where[GPS_LON] = LONGITUDE
    return image


def main() -> None:
    full = with_exif(gps=True, offset=True)
    full.save(HERE / "damp-full.jpg", quality=88, exif=full.getexif())

    # The common case: a tenant with location services off. The time has no offset, so the reader
    # has to decide what it means rather than guess (evidence.md §6: SAST, and the view says so).
    no_gps = with_exif(gps=False, offset=False)
    no_gps.save(HERE / "damp-no-gps.jpg", quality=88, exif=no_gps.getexif())

    # No EXIF at all: saved with nothing attached.
    a_damp_ceiling().save(HERE / "damp-bare.jpg", quality=88)

    for name in ("damp-full.jpg", "damp-no-gps.jpg", "damp-bare.jpg"):
        print(f"   {name}: {(HERE / name).stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
