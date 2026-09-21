"""Build the sample leases from `lease.txt` (T028; docs/design/ocr.md §2, §9).

One text, three forms, the way tenants actually have a lease:

  digital.pdf   a lease emailed by the agent: a real text layer, nothing to read
  scanned.pdf   the same pages run through an office scanner: grey, specked, a little skew
  photo-N.jpg   the same pages photographed on a phone: held at an angle, lit from one side

`lease.txt` is the only text anyone wrote. Each form is derived from it, so the accuracy test
always has something true to compare against (NFR-005), and a page that comes out unreadable is
unreadable because of the form and not because the fixture drifted.

Everything here is deterministic — one seed, fixed geometry — so rebuilding gives the same bytes
and a failing accuracy test means the reader changed, not the paper.

    uv run python tests/fixtures/leases/build.py
"""

import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def photocopied(value: float) -> int:
    """The grey a photocopier leaves on white paper."""
    return min(255, int(value * 0.94) + 12)


def window_light(value: float) -> int:
    """A gradient that dims from one edge of the page to the other."""
    return int(150 + 105 * (value / 255))


def lifted(value: float) -> int:
    """Pull the shaded page back towards white, as a camera's exposure does."""
    return min(255, int(value * 1.35))


def softened(value: float) -> int:
    """Sensor grain, around a mid-grey so it neither darkens nor lightens the page."""
    return int((value - 128) * 0.5) + 128


HERE = Path(__file__).parent
PAGE_BREAK = "--- page 2 ---"
SEED = 20260921
DPI = 200


def pages() -> list[str]:
    """The known text, one entry per page."""
    return [page.strip("\n") for page in (HERE / "lease.txt").read_text().split(PAGE_BREAK)]


def digital(out: Path) -> None:
    """A lease as an agent emails it: 11 pt, A4, a proper text layer."""
    pdf = canvas.Canvas(str(out), pagesize=A4)
    width, height = A4
    for number, page in enumerate(pages()):
        text = pdf.beginText(50, height - 60)
        text.setFont("Helvetica", 11)
        text.setLeading(15.5)
        for line in page.splitlines():
            text.textLine(line)
        pdf.drawText(text)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(width / 2, 35, str(number + 1))
        pdf.showPage()
    pdf.save()


def rendered(source: Path) -> list[Image.Image]:
    """The digital lease as pixels, which is where both the scan and the photo start."""
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-gray", "-png", str(source), str(HERE / "render")],
        check=True,
    )
    images = []
    for path in sorted(HERE.glob("render-*.png")):
        images.append(Image.open(path).convert("L").copy())
        path.unlink()
    return images


def scanned(images: list[Image.Image], out: Path) -> None:
    """An office scanner: a little skew, paper grain, and the grey a photocopier leaves."""
    random.seed(SEED)
    sheets = []
    for image in images:
        sheet = image.rotate(0.4, resample=Image.Resampling.BICUBIC, fillcolor=255, expand=False)
        specks = ImageDraw.Draw(sheet)
        for _ in range(900):
            x = random.randrange(sheet.width)
            y = random.randrange(sheet.height)
            specks.point((x, y), fill=random.randrange(90, 200))
        sheet = sheet.point(photocopied)
        sheets.append(sheet.filter(ImageFilter.GaussianBlur(0.4)))
    sheets[0].save(out, save_all=True, append_images=sheets[1:], resolution=DPI)


def photographed(images: list[Image.Image], stem: str) -> None:
    """A phone photograph of a page on a table: held at an angle, lit from one window, never
    quite in focus, and saved by a camera app that compresses hard.

    This is the hardest of the three forms on purpose. NFR-005 allows a character error rate
    three times higher here than on a scan, and a fixture that looks like a clean render would
    measure nothing.
    """
    random.seed(SEED + 1)
    for number, image in enumerate(images, start=1):
        width, height = image.size

        # Held over the page rather than square to it: the far edge is narrower than the near.
        keystone = width * 0.085
        page = image.transform(
            (width, height),
            Image.Transform.QUAD,
            (keystone, 0, 0, height, width, height, width - keystone, 0),
            resample=Image.Resampling.BICUBIC,
            fillcolor=245,
        )
        page = page.rotate(-1.4, resample=Image.Resampling.BICUBIC, fillcolor=245, expand=False)

        # One window on the left: bright at that edge, falling away to the other.
        gradient = Image.linear_gradient("L").resize((width, height)).rotate(-90, expand=False)
        shading = gradient.point(window_light)
        page = ImageChops.multiply(page, shading).point(lifted)

        # A hand-held camera at arm's length, and the grain a phone sensor leaves indoors.
        page = page.filter(ImageFilter.GaussianBlur(1.1))
        grain = Image.effect_noise((width, height), 14).point(softened)
        page = ImageChops.add(page, grain, scale=1.0, offset=-128)

        page.convert("L").save(HERE / f"{stem}-{number}.jpg", quality=62, dpi=(DPI, DPI))


def main() -> int:
    digital(HERE / "digital.pdf")
    images = rendered(HERE / "digital.pdf")
    scanned(images, HERE / "scanned.pdf")
    photographed(images, "photo")
    made = sorted(p.name for p in HERE.iterdir() if p.suffix in {".pdf", ".jpg"})
    print("built:", ", ".join(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
