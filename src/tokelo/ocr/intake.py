"""What this project will take, and what it refuses (REQ-003; docs/design/api.md §6, ocr.md §4).

REQ-003 is one promise — a PDF or a photograph, at most 20 MB and 30 pages, anything else refused
with the reason — checked at two moments that can see different things:

* **when the URL is asked for** ([api/uploads.py](../api/uploads.py)) there is only the tenant's
  claim: a kind, a content type and a size. What comes back is a POST policy S3 itself holds the
  browser to, so a file over the limit never reaches the bucket.
* **when the worker picks the object up** the bytes are there. A content type is a header somebody
  sent; the first bytes of a file are the file. So the type is read from them, and a PDF's pages
  are counted, which no policy can do.

The table both read is `KINDS`, here, because two lists drifting apart would mean a file the API
promised to take being refused after the tenant had already uploaded it.

**Why the `api` may import this module.** Everything it needs to read a file — `pypdf`, Pillow —
is imported inside the function that uses it. The `api` image has neither installed and never
loads them; it only reads the table.
"""

import io
from dataclasses import dataclass

from tokelo.core.model import DocumentKind

MEGABYTE = 1024 * 1024

# At most 30 pages: REQ-003's limit for a lease (api.md §6), and the ceiling that stops a crafted
# PDF from spending the worker's whole fifteen minutes (ocr.md §Threats). It holds for any PDF.
PAGES = 30

# The first bytes of the formats this project takes. A file that starts with none of them is not
# one of them, whatever it was named and whatever content type was declared for it.
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

# What a refusal calls each of them. A tenant reads this sentence; `image/jpeg` is not a sentence.
NAMES = {
    "application/pdf": "a PDF",
    "image/jpeg": "a JPEG photograph",
    "image/png": "a PNG photograph",
    "text/plain": "a text file",
}


@dataclass(frozen=True)
class Limits:
    """What one kind of upload may be."""

    types: frozenset[str]
    size: int


# api.md §6's table, and the only copy of it (REQ-003). A kind that isn't here can't be uploaded.
KINDS: dict[DocumentKind, Limits] = {
    DocumentKind.LEASE: Limits(
        frozenset({"application/pdf", "image/jpeg", "image/png"}), 20 * MEGABYTE
    ),
    DocumentKind.PHOTO: Limits(frozenset({"image/jpeg", "image/png"}), 20 * MEGABYTE),
    DocumentKind.NOTICE: Limits(
        frozenset({"application/pdf", "image/jpeg", "image/png"}), 20 * MEGABYTE
    ),
    DocumentKind.CHAT: Limits(frozenset({"text/plain"}), 5 * MEGABYTE),
}

UNOPENABLE_PDF = "This PDF couldn't be opened. It may not have finished uploading."
UNOPENABLE_IMAGE = "This image couldn't be opened. It may not have finished uploading."
TOO_MANY_PIXELS = "This image is far larger than a page of a lease, and can't be read."


class Refused(Exception):
    """The file can't be used, and the tenant is told why (REQ-003)."""


@dataclass(frozen=True)
class Accepted:
    """A file this project will read: what it really is, and how many pages of it there are."""

    content_type: str
    pages: int


def accept(kind: DocumentKind, data: bytes) -> Accepted:
    """`data`, checked against what `kind` may be. Raises `Refused`, with what to tell the tenant.

    The content type returned is the one found in the bytes, not the one declared at upload: a
    lease may be sent as `image/jpeg` and be a PDF, and it is the bytes that have to be read.
    """
    limits = KINDS[kind]
    if not data:
        raise Refused("This file is empty.")
    if len(data) > limits.size:
        raise Refused(f"A {kind} may be at most {limits.size // MEGABYTE} MB.")

    found = type_of(data)
    if found is None and "text/plain" in limits.types and is_text(data):
        found = "text/plain"
    if found is None or found not in limits.types:
        allowed = one_of([NAMES[t] for t in sorted(limits.types)])
        raise Refused(
            f"A {kind} has to be {allowed}. Whatever this file was named, its contents are "
            f"something else."
        )

    if found == "application/pdf":
        return Accepted(found, pages_in(data))
    if found == "text/plain":
        return Accepted(found, 1)
    return Accepted(found, image_pages(data))


def type_of(data: bytes) -> str | None:
    """What the file really is, or None when it is nothing this project reads."""
    for signature, content_type in SIGNATURES:
        if data.startswith(signature):
            return content_type
    return None


def is_text(data: bytes) -> bool:
    """A chat export is text: it decodes, and it has no NUL bytes in it. There is no signature
    to check — text doesn't have one — so this is the check."""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def pages_in(data: bytes) -> int:
    """How many pages the PDF has, refusing it if that is more than REQ-003 allows.

    A PDF that won't open is refused, not raised on: the worker would otherwise send the job
    round three times and into the dead-letter queue, and the tenant would never be told why
    (ADR-0007).
    """
    from pypdf import PdfReader

    try:
        count = len(PdfReader(io.BytesIO(data)).pages)
    except Exception as e:
        raise Refused(UNOPENABLE_PDF) from e
    if count < 1:
        raise Refused(UNOPENABLE_PDF)
    if count > PAGES:
        raise Refused(f"A file may be at most {PAGES} pages, and this PDF has {count}.")
    return count


def image_pages(data: bytes) -> int:
    """One photograph is one page — but only once it is shown to decode into one.

    The size is read from the header before any pixel is allocated: a few hundred bytes can claim
    to be thirty thousand pixels square, and the worker has three gigabytes (ocr.md §Threats).
    """
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:
        raise Refused(TOO_MANY_PIXELS) from e
    except Exception as e:
        raise Refused(UNOPENABLE_IMAGE) from e

    with image:
        limit = Image.MAX_IMAGE_PIXELS
        if limit is not None and image.width * image.height > limit:
            raise Refused(TOO_MANY_PIXELS)
        try:
            image.verify()
        except Exception as e:
            raise Refused(UNOPENABLE_IMAGE) from e
    return 1


def one_of(options: list[str]) -> str:
    """Join as `a, b or c`. A refusal is read by a tenant, not parsed by a machine."""
    return " or ".join([", ".join(options[:-1]), options[-1]] if len(options) > 1 else options)
