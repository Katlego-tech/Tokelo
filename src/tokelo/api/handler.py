"""The `api` function's entry point (docs/design/api.md §7). It routes an API Gateway HTTP API
event (payload format 2.0): the kit's health check, the web app and its settings (ADR-0010), and
everything under /api/, which arrives on one route key from behind the JWT authorizer
(infrastructure.md §6). A route it doesn't know is a JSON 404.

Nothing here reads a claim or touches the store: the endpoint modules do that, each starting
from the tenant auth.py hands them (REQ-001)."""

import os
from collections.abc import Callable, Mapping
from typing import Any

from tokelo.api import documents, static
from tokelo.api.auth import Unauthenticated
from tokelo.api.responses import Response, error, json_response

type Event = Mapping[str, Any]


def health(event: Event) -> Response:
    """The kit's smoke check: open, and touching nothing but the function itself."""
    return json_response(200, {"ok": True})


def web_app(event: Event) -> Response:
    return static.serve(str(event.get("rawPath", "/")), os.environ)


def web_config(event: Event) -> Response:
    return static.config(os.environ)


def api(event: Event) -> Response:
    """Everything under /api/. API Gateway sends it all here on one route key, so the path says
    which endpoint it is; the method and the segments after /api/ are the whole of the routing."""
    context = event.get("requestContext", {})
    method = str(context.get("http", {}).get("method", "GET")).upper()
    path = [part for part in str(event.get("rawPath", "")).split("/") if part][1:]
    match method, path:
        case "GET", ["documents"]:
            return documents.list_documents(event)
        case "GET", ["documents", document_id]:
            return documents.get_document(event, document_id)
    return error(404, "not_found", "No such route.")


ROUTES: dict[str, Callable[[Event], Response]] = {
    "GET /health": health,
    "GET /config.json": web_config,
    "GET /": web_app,
    "GET /{proxy+}": web_app,
    "ANY /api/{proxy+}": api,
}


def handler(event: Event, context: object = None) -> Response:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return error(404, "not_found", "No such route.")
    try:
        return route(event)
    except Unauthenticated:
        # API Gateway refuses these first (infrastructure.md §6); reaching here means a route
        # was left open by mistake, and the answer is still no.
        return error(401, "unauthenticated", "Sign in to use this.")
