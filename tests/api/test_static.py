"""The `api` serves the web app and its settings (ADR-0010; docs/design/web.md §6, Threats)."""

import base64
import json

import pytest

from tokelo.api.handler import handler

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


@pytest.fixture
def web_root(tmp_path, monkeypatch):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Tokelo</title>")
    (root / "assets" / "index-abc123.js").write_text("console.log('app')")
    (root / "assets" / "logo-def456.png").write_bytes(PNG)
    (tmp_path / "secret.txt").write_text("outside the web root")
    monkeypatch.setenv("TOKELO_WEB_ROOT", str(root))
    for name in (
        "AWS_REGION",
        "TOKELO_USER_POOL_ID",
        "TOKELO_CLIENT_ID",
        "TOKELO_DOCUMENTS_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)
    return root


def get(path: str) -> dict:
    route = {"/": "GET /", "/health": "GET /health", "/config.json": "GET /config.json"}
    return handler(
        {"version": "2.0", "routeKey": route.get(path, "GET /{proxy+}"), "rawPath": path}
    )


def test_the_root_serves_the_app_uncached_with_its_security_headers(web_root):
    response = get("/")
    assert response["statusCode"] == 200
    headers = response["headers"]
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["strict-transport-security"].startswith("max-age=31536000")
    assert headers["x-content-type-options"] == "nosniff"
    assert response["body"] == "<!doctype html><title>Tokelo</title>"


def test_a_hashed_asset_is_cached_for_a_year(web_root):
    response = get("/assets/index-abc123.js")
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "text/javascript; charset=utf-8"
    assert response["headers"]["cache-control"] == "public, max-age=31536000, immutable"


def test_an_app_route_falls_back_to_the_app(web_root):
    response = get("/lease/7d2f")
    assert response["statusCode"] == 200
    assert response["body"] == "<!doctype html><title>Tokelo</title>"


@pytest.mark.parametrize("path", ["/assets/missing-000.js", "/favicon.ico"])
def test_a_missing_file_is_a_404_not_the_app(web_root, path):
    response = get(path)
    assert response["statusCode"] == 404
    assert "Tokelo" not in response["body"]


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"]
)
def test_nothing_outside_the_web_root_is_served(web_root, path):
    response = get(path)
    assert response["statusCode"] == 404
    assert "outside the web root" not in response["body"]


def test_a_binary_file_is_base64_encoded(web_root):
    response = get("/assets/logo-def456.png")
    assert response["headers"]["content-type"] == "image/png"
    assert response["isBase64Encoded"] is True
    assert base64.b64decode(response["body"]) == PNG


def test_an_unknown_api_path_is_a_json_404_not_the_app(web_root):
    response = get("/api/nothing-here")
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"]["code"] == "not_found"


def test_the_csp_lets_the_app_reach_only_itself_cognito_and_the_documents_bucket(
    web_root, monkeypatch
):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("TOKELO_DOCUMENTS_BUCKET", "tokelo-staging-documents-123456789012")
    csp = get("/")["headers"]["content-security-policy"]
    connect = next(d for d in csp.split("; ") if d.startswith("connect-src"))
    assert connect.split()[1:] == [
        "'self'",
        "https://cognito-idp.eu-west-1.amazonaws.com",
        "https://tokelo-staging-documents-123456789012.s3.eu-west-1.amazonaws.com",
    ]


def test_config_json_comes_from_the_functions_environment(web_root, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("TOKELO_USER_POOL_ID", "eu-west-1_Example")
    monkeypatch.setenv("TOKELO_CLIENT_ID", "example-client-id")
    response = get("/config.json")
    assert response["statusCode"] == 200
    assert response["headers"]["cache-control"] == "no-store, no-cache, must-revalidate"
    assert json.loads(response["body"]) == {
        "region": "eu-west-1",
        "user_pool_id": "eu-west-1_Example",
        "client_id": "example-client-id",
    }


def test_config_json_without_its_settings_says_so(web_root):
    response = get("/config.json")
    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"]["code"] == "not_configured"


def test_without_the_built_app_the_root_says_so(web_root):
    (web_root / "index.html").unlink()
    response = get("/")
    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"]["code"] == "web_app_missing"


# Every response, not only the page: a ZAP baseline against staging (v0.1.0, 2026-09-20) warned
# that the assets and the 404s carried none of these.
@pytest.mark.parametrize(
    "path", ["/", "/assets/index-abc123.js", "/assets/missing-000.js", "/api/nothing-here"]
)
def test_every_response_carries_the_transport_headers(web_root, path):
    headers = get(path)["headers"]
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    # The app needs none of these, so none of them is available to anything it loads.
    policy = headers["permissions-policy"]
    assert "camera=()" in policy and "geolocation=()" in policy and "microphone=()" in policy


@pytest.mark.parametrize("path", ["/", "/lease/7d2f", "/assets/missing-000.js"])
def test_nothing_but_a_hashed_asset_may_be_stored(web_root, path):
    assert get(path)["headers"]["cache-control"] == "no-store, no-cache, must-revalidate"
