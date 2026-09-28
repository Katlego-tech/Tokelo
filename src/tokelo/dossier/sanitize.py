"""A lease's or a notice's own pages, made safe to copy into a dossier (docs/design/dossier.md §6,
"Copying a PDF's pages in"; §Threats).

A notice is whatever the landlord sent, and a PDF can carry more than its pages. The dossier goes
to a Tribunal or a court, so none of these may come with it:
- JavaScript, run when the file or a page opens
- links that launch a program, open an address or submit a form
- form fields
- files attached inside it

Most of those hang off the document itself (`/OpenAction`, `/Names`, `/AcroForm`), and only the
pages are copied, so they stay behind with the original. The rest are on a page:
- its own open and close actions, `/AA`
- its annotations. A link, a form field, an attachment, or a movie or sound, is removed whole. It
  exists to act or to carry a file, and it shows nothing a reader needs. Any other annotation (a
  note, a highlight, a stamp) keeps its place, without an action of its own.

The page content, what the page shows, is copied exactly as it is. That is the evidence.
"""

import io

from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, NameObject

# The annotations that act or carry, rather than show.
REMOVED = frozenset(
    {"/Link", "/Widget", "/FileAttachment", "/Screen", "/Movie", "/Sound", "/RichMedia", "/3D"}
)
# What makes any other annotation act: its action, and its additional actions.
ACTIONS = ("/A", "/AA")


class Unreadable(Exception):
    """The file isn't a PDF this can open: damaged, or locked with a password."""


def pages(data: bytes) -> list[PageObject]:
    """Every page of the PDF, sanitised, in order. Raises Unreadable."""
    return [clean(page) for page in _reader(data).pages]


def count(data: bytes) -> int:
    """How many pages the PDF has. Raises Unreadable."""
    return len(_reader(data).pages)


def clean(page: PageObject) -> PageObject:
    """The page, with its actions removed and only annotations that show kept."""
    page.pop(NameObject("/AA"), None)
    if "/Annots" not in page:
        return page
    kept = ArrayObject()
    for reference in page["/Annots"]:  # type: ignore[union-attr]
        annotation = reference.get_object()
        if annotation.get("/Subtype") in REMOVED:
            continue
        for name in ACTIONS:
            annotation.pop(NameObject(name), None)
        kept.append(reference)
    if kept:
        page[NameObject("/Annots")] = kept
    else:
        del page["/Annots"]
    return page


def _reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        # A password to open it is one Tokelo doesn't have. One that only guards against editing
        # opens with an empty password, and its pages are copied like any other's.
        locked = reader.is_encrypted and not reader.decrypt("")
        if not locked:
            len(reader.pages)  # pypdf reads lazily: a damaged file shows it here
    except Exception as damaged:
        # These are a stranger's bytes, and pypdf can fail on them in more ways than it names
        # (PdfReadError, but also KeyError, struct and zlib errors, a missing AES provider). Any
        # of them means the same thing here: this file's pages can't be copied.
        raise Unreadable(f"the PDF can't be read: {type(damaged).__name__}") from damaged
    if locked:
        raise Unreadable("the PDF is locked with a password")
    return reader
