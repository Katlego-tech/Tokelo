"""The shapes of the `api`'s responses (docs/design/api.md §6): API Gateway HTTP API, payload
format 2.0."""

import json
from typing import Any

type Response = dict[str, Any]


def json_response(status: int, body: object, headers: dict[str, str] | None = None) -> Response:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def error(status: int, code: str, message: str) -> Response:
    return json_response(status, {"error": {"code": code, "message": message}})
