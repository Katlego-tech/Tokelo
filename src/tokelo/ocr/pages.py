"""Reading one page of a lease (ADR-0009; docs/design/ocr.md §2, §4; REQ-004, NFR-004, NFR-005).

The order matters and is ADR-0009's: **a PDF's text layer first**. A lease emailed by an agent
already carries its words, and taking them is exact, instant and free. Only a page with no text
layer — a scan, or a photograph — is rendered and put through Tesseract, which is slower and
never exact.

Preprocessing is where a photograph is won or lost. A page shot on a phone arrives keystoned,
lit from one side and soft, and Tesseract reads that badly. What it reads well is a large, flat,
high-contrast page, so that is what it is given: upscaled, its uneven lighting divided out, and
thresholded to black on white.

A page that comes back with too little text to be a page of a lease is reported unreadable, by
its number, rather than passed on as if it had been read (REQ-004). A tenant is told which page
failed; nothing is guessed at.
"""

import io
import re
from dataclasses import dataclass
from typing import Literal

Source = Literal["text_layer", "ocr"]

# A page of a lease has words on it. Fewer than this many characters means the page was blank,
# or that reading it failed in a way that produced specks rather than text.
ENOUGH = 120
# The text layer is trusted when it holds this much; below it the page is rendered and read.
TEXT_LAYER_IS_REAL = 60

LANGUAGE = "eng"  # English only, and no other model is installed (ADR-0009)
RENDER_SCALE = 300 / 72  # 300 dpi, which is what Tesseract is happiest with
WORD = re.compile(r"[A-Za-z]{2,}")


@dataclass(frozen=True)
class Read:
    """What one page gave up."""

    text: str
    source: Source
    readable: bool


def read(document: bytes, content_type: str, page: int) -> Read:
    """Page `page` (1-based) of `document`, as text.

    `content_type` is what the tenant's upload declared and the worker confirmed (T030):
    a PDF is tried as a text layer first, an image goes straight to Tesseract.

    A page the document doesn't have comes back empty and unreadable rather than raising.
    """
    if content_type == "application/pdf":
        # A job for a page the document doesn't have: a redelivery for a lease since replaced,
        # or a page count that moved. There is nothing to read and nothing to render — rendering
        # it raises, and a worker that raises on a message it can never do sends that message
        # round three times and into the dead-letter queue (ADR-0007).
        if not 1 <= page <= page_count(document):
            return Read(text="", source="text_layer", readable=False)

        layer = text_layer(document, page)
        if len(layer.strip()) >= TEXT_LAYER_IS_REAL:
            return Read(text=tidy(layer), source="text_layer", readable=True)
        image = rendered(document, page)
    else:
        from PIL import Image

        image = Image.open(io.BytesIO(document))

    text = tidy(transcribe(image))
    return Read(text=text, source="ocr", readable=is_a_page(text))


def text_layer(document: bytes, page: int) -> str:
    """What the PDF already says about itself, if anything."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(document))
    if page < 1 or page > len(reader.pages):
        return ""
    return reader.pages[page - 1].extract_text() or ""


def page_count(document: bytes) -> int:
    """How many pages the PDF has — what T030 checks a lease's length against."""
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(document)).pages)


def rendered(document: bytes, page: int):
    """One page of a PDF as an image, at the size Tesseract reads best."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(io.BytesIO(document))
    try:
        # pypdfium2 types `scale` as an int; it is a multiplier and takes a float, which is how
        # 300 dpi is asked for (300/72). Measured on the sample leases, not assumed.
        return (
            pdf[page - 1]
            .render(scale=RENDER_SCALE)  # pyright: ignore[reportArgumentType]
            .to_pil()
            .convert("L")
        )
    finally:
        pdf.close()


def prepared(image):
    """A photographed page, made into something Tesseract can read.

    Three things, in order, each earning its place on the sample photographs (T028):

    1. **Upscale a small image.** Tesseract wants letters around 30 px tall; a phone photo of a
       whole A4 page gives it fewer.
    2. **Divide out the lighting.** A page lit from one window is bright at one edge and grey at
       the other, and a single threshold over the whole page loses one end or the other. Dividing
       the page by a heavily blurred copy of itself removes the gradient and keeps the letters.
    3. **Threshold.** Black on white, which is what the engine was trained on.
    """
    from PIL import Image, ImageFilter

    grey = image.convert("L")
    if min(grey.size) < 1500:
        scale = 1500 / min(grey.size)
        grey = grey.resize(
            (int(grey.width * scale), int(grey.height * scale)), Image.Resampling.LANCZOS
        )

    background = grey.filter(ImageFilter.GaussianBlur(25))
    flattened = Image.new("L", grey.size)
    flattened.putdata(
        [
            min(255, int(255 * (value + 1) / (light + 1)))
            for value, light in zip(grey.getdata(), background.getdata(), strict=True)
        ]
    )
    return flattened.point(inked, mode="L")


def inked(value: float) -> int:
    """Black where there is ink, white where there is paper. The cut sits high because the page
    has already been flattened: what is left below it is a letter, not a shadow."""
    return 0 if value < 200 else 255


def transcribe(image) -> str:
    """Tesseract, on a page prepared for it. `--psm 6` says: one block of text, laid out in
    lines — which is what a page of a lease is, and stops the engine hunting for columns."""
    import pytesseract

    return pytesseract.image_to_string(prepared(image), lang=LANGUAGE, config="--psm 6")


def tidy(text: str) -> str:
    """Trailing spaces and runs of blank lines go; the line breaks stay, because the clause
    splitter reads them (clauses.py)."""
    lines = [line.rstrip() for line in text.replace("\f", "\n").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def is_a_page(text: str) -> bool:
    """Whether what came back is a page of a lease or the noise of a failed read."""
    return len(text) >= ENOUGH and len(WORD.findall(text)) >= 20
