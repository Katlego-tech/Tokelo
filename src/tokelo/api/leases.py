"""A lease's flags (docs/design/api.md §6; REQ-001, REQ-004 to REQ-007).

The work is already done when a request gets here: the `ocr` worker read the lease, split it,
ran the rules and stored the result (T057). This endpoint only decides what leaves the function,
and the whole of that decision is api.md §6's `LeaseFlags`.

Two answers other than the flags themselves matter as much as the flags do:

* **409 while the lease is still being read.** Half a lease's clauses would read as a lease with
  fewer problems than it has, which is the one wrong answer this endpoint could give.
* **404 for someone else's lease.** The tenant comes from the token and goes to the store as the
  partition key, so another tenant's lease and a lease that never existed are the same answer.
  A 403 would confirm it exists, which is the other tenant's business and nobody else's
  (REQ-001).
"""

from collections.abc import Mapping
from typing import Any

from tokelo.api import views
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core.model import DocumentKind, LeaseStatus
from tokelo.core.store import Store

type Event = Mapping[str, Any]

STILL_READING = "This lease is still being read. Its flags will be here shortly."

_store: Store | None = None


def store_for() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def lease_flags(event: Event, document_id: str) -> Response:
    """GET /api/leases/{id}/flags."""
    tenant = tenant_of(event)
    stored = store_for().get_document(tenant, document_id)
    if stored is None or stored.document.kind is not DocumentKind.LEASE:
        return error(404, "not_found", "No such lease.")

    lease = stored.document.lease
    if lease is None or lease.status is LeaseStatus.READING:
        return error(409, "still_reading", STILL_READING)

    return json_response(200, views.lease_flags(stored))
