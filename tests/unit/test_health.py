"""The `api` answers the kit's smoke check, and any route it doesn't know with a JSON 404
(docs/design/api.md §6). Events are API Gateway HTTP API payloads, format 2.0."""

import json

from tokelo.api.handler import handler


def http_event(route_key: str) -> dict:
    method, _, path = route_key.partition(" ")
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
    }


def test_health_answers_ok():
    response = handler(http_event("GET /health"))
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/json"
    assert json.loads(response["body"]) == {"ok": True}


def test_an_unknown_route_is_a_json_404():
    response = handler(http_event("GET /nowhere"))
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"]["code"] == "not_found"
