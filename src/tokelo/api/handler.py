"""The `api` function's entry point (docs/design/api.md §7). It routes an API Gateway HTTP API
event (payload format 2.0) on its route key, and answers a route it doesn't know with a JSON
404."""

import json
from collections.abc import Callable, Mapping
from typing import Any

type Event = Mapping[str, Any]
type Response = dict[str, Any]


def json_response(status: int, body: object) -> Response:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def health(event: Event) -> Response:
    """The kit's smoke check: open, and touching nothing but the function itself."""
    return json_response(200, {"ok": True})


ROUTES: dict[str, Callable[[Event], Response]] = {"GET /health": health}


def handler(event: Event, context: object = None) -> Response:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return json_response(404, {"error": {"code": "not_found", "message": "No such route."}})
    return route(event)
