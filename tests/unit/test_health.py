"""The health checks the kit's release runs. The `api` answers `GET /health`, and any route it
doesn't know with a JSON 404 (docs/design/api.md §6); its events are API Gateway HTTP API
payloads, format 2.0. Each worker answers the kit's health contract: invoked with
{"realm": "health"}, it returns {"ok": true} (docs/design/infrastructure.md §4)."""

import importlib
import json

import pytest

from tokelo.api.handler import handler
from tokelo.core.health import UnknownEvent

WORKERS = ["ocr", "evidence", "dossier"]


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


@pytest.mark.parametrize("worker", WORKERS)
def test_each_worker_answers_the_health_contract(worker):
    worker_handler = importlib.import_module(f"tokelo.{worker}.handler").handler
    assert worker_handler({"realm": "health"}) == {"ok": True}


@pytest.mark.parametrize("worker", WORKERS)
def test_each_worker_refuses_an_event_it_does_not_know(worker):
    worker_handler = importlib.import_module(f"tokelo.{worker}.handler").handler
    with pytest.raises(UnknownEvent):
        worker_handler({"Records": [{"eventSource": "aws:sqs", "body": "{}"}]})
