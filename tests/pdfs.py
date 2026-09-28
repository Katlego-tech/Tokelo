"""PDFs made for tests: a plain one, and a hostile one carrying every hazard a copied page must
lose (docs/design/dossier.md §6). The sanitiser's tests and the dossier's both use them, so
both prove the same thing about the same file."""

import io

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    TextStringObject,
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

WORDS = "NOTICE TO VACATE THE PREMISES"

# What must not survive the copy, as the names PDF spells them.
HAZARDS = [
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/URI",
    b"/SubmitForm",
    b"/EmbeddedFile",
    b"/FileAttachment",
    b"/Widget",
    b"/AcroForm",
    b"/OpenAction",
]


def plain_page(words: str = WORDS, pages: int = 1) -> bytes:
    out = io.BytesIO()
    drawing = canvas.Canvas(out, pagesize=A4)
    for n in range(1, pages + 1):
        drawing.drawString(72, 720, f"{words} - page {n}")
        drawing.showPage()
    drawing.save()
    return out.getvalue()


def action(kind: str, **fields: object) -> DictionaryObject:
    made = DictionaryObject({NameObject("/S"): NameObject(kind)})
    for key, value in fields.items():
        made[NameObject(f"/{key}")] = (
            value if not isinstance(value, str) else TextStringObject(value)
        )
    return made


def annotation(writer: PdfWriter, subtype: str, **fields: object) -> object:
    made = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject(subtype),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (72, 600, 300, 640)]),
        }
    )
    for key, value in fields.items():
        made[NameObject(f"/{key}")] = value  # type: ignore[assignment]
    return writer._add_object(made)


def hostile() -> bytes:
    """A two-page notice with every hazard dossier.md §6 names, and a harmless note beside them."""
    writer = PdfWriter(clone_from=io.BytesIO(plain_page(pages=2)))
    page = writer.pages[0]

    # JavaScript when the document opens, and when the page does.
    writer.add_js("app.alert('opened');")
    page[NameObject("/AA")] = DictionaryObject(
        {NameObject("/O"): action("/JavaScript", JS="app.alert('page');")}
    )
    # Links: one runs a program, one opens an address, one runs JavaScript.
    links = [
        annotation(writer, "/Link", A=action("/Launch", F="calc.exe")),
        annotation(writer, "/Link", A=action("/URI", URI="https://example.invalid/track")),
        annotation(writer, "/Link", A=action("/JavaScript", JS="app.alert('link');")),
    ]
    # A form field, and a form that submits itself somewhere.
    field = annotation(
        writer,
        "/Widget",
        FT=NameObject("/Tx"),
        T=TextStringObject("tenant_name"),
        AA=DictionaryObject({NameObject("/K"): action("/SubmitForm", F="https://x.invalid")}),
    )
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject([field])}
    )
    # A file attached to the document, and one attached to the page.
    writer.add_attachment("invoice.exe", b"MZ this is not an invoice")
    attached = annotation(writer, "/FileAttachment", FS=TextStringObject("payload.bin"))
    # A text note: an annotation, but not one that acts. It keeps its place, without its action.
    note = annotation(
        writer,
        "/Text",
        Contents=TextStringObject("received 1 October"),
        A=action("/JavaScript", JS="app.alert('note');"),
    )
    page[NameObject("/Annots")] = ArrayObject([*links, field, attached, note])
    writer._root_object[NameObject("/OpenAction")] = action("/JavaScript", JS="app.alert(1);")

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
