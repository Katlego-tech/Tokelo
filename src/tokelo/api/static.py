"""The web app and its settings, served by the `api` function (ADR-0010; docs/design/web.md).

The built app (web/dist) is copied into the image. Hashed files under assets/ are cached for a
year; index.html is never cached and answers any app route; every HTML response carries the
security headers. Nothing outside the web root is ever served, and no /api/ path is answered
with the app."""

import base64
from collections.abc import Mapping
from pathlib import Path

from tokelo.api.responses import Response, error, json_response

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
TEXT = ("text/", "application/json", "image/svg+xml")
IMMUTABLE = "public, max-age=31536000, immutable"


def web_root(env: Mapping[str, str]) -> Path:
    default = Path(env.get("LAMBDA_TASK_ROOT", "/var/task")) / "web"
    return Path(env.get("TOKELO_WEB_ROOT", str(default)))


def content_security_policy(env: Mapping[str, str]) -> str:
    """The app talks to itself, to Cognito, and to the documents bucket for uploads."""
    connect = ["'self'"]
    region = env.get("AWS_REGION")
    if region:
        connect.append(f"https://cognito-idp.{region}.amazonaws.com")
        bucket = env.get("TOKELO_DOCUMENTS_BUCKET")
        if bucket:
            connect.append(f"https://{bucket}.s3.{region}.amazonaws.com")
    return "; ".join(
        [
            "default-src 'self'",
            "connect-src " + " ".join(connect),
            "img-src 'self' blob: data:",
            "style-src 'self'",
            "script-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


def file_response(path: Path, cache_control: str, env: Mapping[str, str]) -> Response:
    content_type = TYPES.get(path.suffix, "application/octet-stream")
    headers = {
        "content-type": content_type,
        "cache-control": cache_control,
        "x-content-type-options": "nosniff",
    }
    if content_type.startswith("text/html"):
        headers |= {
            "content-security-policy": content_security_policy(env),
            "strict-transport-security": "max-age=31536000; includeSubDomains",
            "referrer-policy": "no-referrer",
        }
    data = path.read_bytes()
    if content_type.startswith(TEXT):
        return {"statusCode": 200, "headers": headers, "body": data.decode("utf-8")}
    return {
        "statusCode": 200,
        "headers": headers,
        "body": base64.b64encode(data).decode("ascii"),
        "isBase64Encoded": True,
    }


def not_found() -> Response:
    return {
        "statusCode": 404,
        "headers": {
            "content-type": "text/plain; charset=utf-8",
            "x-content-type-options": "nosniff",
        },
        "body": "Not found.",
    }


def serve(path: str, env: Mapping[str, str]) -> Response:
    if path == "/api" or path.startswith("/api/"):
        return error(404, "not_found", "No such route.")
    root = web_root(env).resolve()
    index = root / "index.html"
    if not index.is_file():
        return error(503, "web_app_missing", "This image has no built web app.")
    parts = [part for part in path.split("/") if part]
    if any(part.startswith(".") or "%" in part or "\\" in part for part in parts):
        return not_found()
    if not parts:
        return file_response(index, "no-cache", env)
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root):
        return not_found()
    if candidate.is_file():
        cache = IMMUTABLE if parts[0] == "assets" else "public, max-age=3600"
        return file_response(candidate, "no-cache" if candidate == index else cache, env)
    if "." not in parts[-1]:
        return file_response(index, "no-cache", env)  # an app route: the app handles it
    return not_found()


def config(env: Mapping[str, str]) -> Response:
    """The per-environment settings the app reads at start, so one image serves both
    environments (ADR-0010)."""
    settings = {
        "region": env.get("AWS_REGION"),
        "user_pool_id": env.get("TOKELO_USER_POOL_ID"),
        "client_id": env.get("TOKELO_CLIENT_ID"),
    }
    if not all(settings.values()):
        return error(503, "not_configured", "This function has no web app settings.")
    return json_response(200, settings, {"cache-control": "no-store"})
