"""The shapes of the `api`'s responses (docs/design/api.md §6): API Gateway HTTP API, payload
format 2.0.

Every response carries SECURITY, whatever it is: a page, an asset, a JSON body or a 404. The
headers that describe the connection are the browser's instructions for the whole origin, so a
response that leaves them out weakens the ones that don't (a ZAP baseline against staging found
exactly that on the assets and the 404s, v0.1.0)."""

import json
from typing import Any

type Response = dict[str, Any]

# A JSON answer is per-tenant and never worth keeping. All three directives, because a
# store that honours only one of them still keeps it (ZAP rule 10015).
NO_STORE = "no-store, no-cache, must-revalidate"

# What the app is allowed to use: nothing. Listed rather than left out, so a feature that wants a
# camera has to change this line and say why (docs/design/web.md §6).
PERMISSIONS = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()"
)

SECURITY = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": PERMISSIONS,
    # The app is alone in its browsing context group, and nothing else may embed what it serves.
    # Cross-Origin-Embedder-Policy is deliberately not set: require-corp would block the tenant's
    # own photos, which come from S3 by pre-signed URL (docs/release/zap-rules.tsv, rule 90004).
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}


def secured(headers: dict[str, str]) -> dict[str, str]:
    """`headers` with the security headers under them: a caller may override none of them."""
    return {**headers, **SECURITY}


def json_response(status: int, body: object, headers: dict[str, str] | None = None) -> Response:
    return {
        "statusCode": status,
        "headers": secured(
            {"content-type": "application/json", "cache-control": NO_STORE, **(headers or {})}
        ),
        "body": json.dumps(body),
    }


def error(status: int, code: str, message: str) -> Response:
    return json_response(status, {"error": {"code": code, "message": message}})
