"""The `api` function's entry point (docs/design/api.md §7). It routes an API Gateway HTTP API
event (payload format 2.0) on its route key: the kit's health check, the web app and its
settings (ADR-0010), and answers a route it doesn't know with a JSON 404."""

import os
from collections.abc import Callable, Mapping
from typing import Any

from tokelo.api import static
from tokelo.api.responses import Response, error, json_response

type Event = Mapping[str, Any]


def health(event: Event) -> Response:
    """The kit's smoke check: open, and touching nothing but the function itself."""
    return json_response(200, {"ok": True})


def web_app(event: Event) -> Response:
    return static.serve(str(event.get("rawPath", "/")), os.environ)


def web_config(event: Event) -> Response:
    return static.config(os.environ)


ROUTES: dict[str, Callable[[Event], Response]] = {
    "GET /health": health,
    "GET /config.json": web_config,
    "GET /": web_app,
    "GET /{proxy+}": web_app,
}


def handler(event: Event, context: object = None) -> Response:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return error(404, "not_found", "No such route.")
    return route(event)
