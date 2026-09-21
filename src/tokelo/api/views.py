"""The shapes that leave the function (docs/design/api.md §6, "The views").

A view is built from a stored item and never the other way round: what the store holds may grow
fields the API doesn't promise, and a tenant's answer shouldn't change because an item did.

"not recorded" is deliberate. A photo that carries no capture time doesn't get a guessed one, an
empty string or a null the app has to interpret — it says so, in the words the screen shows
(REQ-009)."""

from typing import Any

from tokelo.core.model import Clause, Document, DocumentKind, StoredDocument
from tokelo.ocr.flags import NO_ISSUE

NOT_RECORDED = "not recorded"

# On every answer that carries law, in the same words wherever it appears (api.md §6; the
# non-negotiable in PLAN.md). Tokelo says what the law requires; it does not advise anyone.
NOTICE = "This is legal information, not legal advice."


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


def lease_flags(stored: StoredDocument) -> dict[str, Any]:
    """api.md §6's `LeaseFlags`: the whole lease, clause by clause, with the notice.

    The pages nobody could read are named by their numbers, so a tenant re-photographs the one
    page that failed rather than the lease (REQ-004).
    """
    lease = stored.document.lease
    return {
        "status": str(lease.status) if lease else "",
        # The count the worker took from the file itself (REQ-003), which is what makes the next
        # line mean something: "page 3 couldn't be read" is a different thing in a four-page
        # lease and a thirty-page one.
        "page_count": lease.page_count if lease else 0,
        "unreadable_pages": sorted(page.number for page in stored.pages if not page.readable),
        "notice": NOTICE,
        "clauses": [clause_view(c) for c in sorted(stored.clauses, key=lambda c: c.ordinal)],
    }


def clause_view(clause: Clause) -> dict[str, Any]:
    """One clause as a tenant is shown it. A clause nothing matched carries the finding instead
    of a flag — never that it is lawful, which is REQ-007 and the reason `NO_ISSUE` is imported
    from where the worker wrote it rather than spelt out again here."""
    view: dict[str, Any] = {
        "label": clause.label,
        "first_page": clause.first_page,
        "text": clause.text,
        "flags": [flag_view(f) for f in clause.flags],
    }
    if not clause.flags:
        view["finding"] = NO_ISSUE
    return view


def flag_view(flag: dict[str, Any]) -> dict[str, Any]:
    """What the tenant reads and what it rests on. The catalogue's version is kept on the stored
    flag so an old answer stays readable, and is not part of what the API promises."""
    return {
        "rule_id": flag.get("rule_id", ""),
        "explanation": flag.get("explanation", ""),
        "sections": flag.get("sections", []),
    }
