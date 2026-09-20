"""The bucket's key layout (docs/design/api.md §6), used by the `api` and the workers alike.

A key is not a name but a routing decision: EventBridge matches on its shape to choose the queue
(infrastructure.md §6), and a worker reads the tenant and the document straight out of it. So the
layout lives in one place, with the code that builds a key next to the code that reads it back —
the two drifting apart would send a tenant's lease to the wrong worker, or to none.

    uploads/<tenant>/<kind>/<document>   what the tenant uploads, straight from the browser
    jobs/page/<document>/<n>.json        one page of a lease, for the ocr worker
    jobs/dossier/<dossier>.json          a dossier to compile
    dossiers/<tenant>/<dossier>.pdf      the compiled dossier
"""

import re
from dataclasses import dataclass

from tokelo.core.model import DocumentKind

# The IDs in a key are UUIDs this project wrote. Anything else never came from here.
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UPLOAD = re.compile(rf"^uploads/(?P<tenant>{UUID})/(?P<kind>[a-z]+)/(?P<document>{UUID})$")
PAGE_JOB = re.compile(rf"^jobs/page/(?P<document>{UUID})/(?P<page>\d+)\.json$")
DOSSIER_JOB = re.compile(rf"^jobs/dossier/(?P<dossier>{UUID})\.json$")


@dataclass(frozen=True)
class Parsed:
    """What a key says about itself: whichever of these the shape carries."""

    tenant_id: str | None = None
    kind: DocumentKind | None = None
    document_id: str | None = None
    page: int | None = None


def upload_key(tenant_id: str, kind: DocumentKind, document_id: str) -> str:
    return f"uploads/{tenant_id}/{kind}/{document_id}"


def page_job_key(document_id: str, page: int) -> str:
    return f"jobs/page/{document_id}/{page}.json"


def dossier_job_key(dossier_id: str) -> str:
    return f"jobs/dossier/{dossier_id}.json"


def dossier_key(tenant_id: str, dossier_id: str) -> str:
    return f"dossiers/{tenant_id}/{dossier_id}.pdf"


def parse(key: str) -> Parsed | None:
    """What this key is, or None when it is not one this project writes."""
    if upload := UPLOAD.match(key):
        try:
            kind = DocumentKind(upload["kind"])
        except ValueError:
            return None
        return Parsed(tenant_id=upload["tenant"], kind=kind, document_id=upload["document"])
    if page := PAGE_JOB.match(key):
        return Parsed(document_id=page["document"], page=int(page["page"]))
    if dossier := DOSSIER_JOB.match(key):
        return Parsed(document_id=dossier["dossier"])
    return None
