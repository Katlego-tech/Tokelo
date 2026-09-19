"""realm.toml declares the four services the release builds and the AWS bootstrap creates image
repositories for (ADR-0002, ADR-0010; docs/design/infrastructure.md §6)."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def services() -> dict[str, dict]:
    config = tomllib.loads((ROOT / "realm.toml").read_text())
    return {s["name"]: s for s in config.get("service", [])}


def test_the_four_services_run_on_lambda():
    declared = services()
    assert list(declared) == ["api", "ocr", "evidence", "dossier"]
    assert all(s["runtime"] == "lambda" for s in declared.values())


def test_the_api_is_the_web_service_and_serves_the_web_app():
    api = services()["api"]
    assert api.get("kind", "web") == "web"
    assert api["health"] == "/health"
    assert api["ui"] is True  # pa11y and ZAP check the web app it serves (ADR-0010)


def test_the_workers_are_workers():
    declared = services()
    for name in ("ocr", "evidence", "dossier"):
        assert declared[name]["kind"] == "worker"
        assert "health" not in declared[name] and not declared[name].get("ui", False)


def test_each_service_builds_from_its_own_dockerfile_at_the_root():
    for name, service in services().items():
        assert service["context"] == "."
        assert service["dockerfile"] == f"services/{name}/Dockerfile"
        assert (ROOT / service["dockerfile"]).is_file()
