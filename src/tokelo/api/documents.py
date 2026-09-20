"""The documents a tenant owns (docs/design/api.md §6): the list, and one of them.

Every call here starts with the tenant from the token's claims and hands it to the store as the
partition key, so "another tenant's document" and "no such document" are the same answer — a 404
(REQ-001). Telling them apart would confirm that a document exists, which is the other tenant's
business and nobody else's."""

from collections.abc import Mapping
from typing import Any

from tokelo.api import views
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core.store import Store

type Event = Mapping[str, Any]

_store: Store | None = None


def store_for() -> Store:
    """One Store per container, built on first use and reused: a Lambda that answers a second
    request should not build a client again (api.md §4)."""
    global _store
    if _store is None:
        _store = Store()
    return _store


def list_documents(event: Event) -> Response:
    tenant = tenant_of(event)
    documents = store_for().list_documents(tenant)
    return json_response(200, {"documents": [views.document_view(d) for d in documents]})


def get_document(event: Event, document_id: str) -> Response:
    tenant = tenant_of(event)
    stored = store_for().get_document(tenant, document_id)
    if stored is None:
        return error(404, "not_found", "No such document.")
    return json_response(200, views.document_view(stored.document))
