"""The shapes that leave the function (docs/design/api.md §6, "The views").

A view is built from a stored item and never the other way round: what the store holds may grow
fields the API doesn't promise, and a tenant's answer shouldn't change because an item did.

"not recorded" is deliberate. A photo that carries no capture time doesn't get a guessed one, an
empty string or a null the app has to interpret — it says so, in the words the screen shows
(REQ-009)."""

from typing import Any

from tokelo.core.model import Document, DocumentKind

NOT_RECORDED = "not recorded"


def document_view(document: Document) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": document.id,
        "kind": str(document.kind),
        "status": str(document.status),
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "stored_at": document.stored_at,
        "failure_reason": document.failure_reason,
    }
    if document.kind is DocumentKind.PHOTO:
        capture = document.capture
        view["capture"] = {
            "captured_at": (capture.captured_at if capture else None) or NOT_RECORDED,
            "device": (capture.device if capture else None) or NOT_RECORDED,
            "latitude": _number(capture.latitude if capture else None),
            "longitude": _number(capture.longitude if capture else None),
        }
    return view


def _number(value: float | None) -> float | str:
    return NOT_RECORDED if value is None else value
