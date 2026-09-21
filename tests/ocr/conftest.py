"""Running the reader where Tesseract is (T029).

The `ocr` image carries Tesseract 5.5.0 from Debian trixie, which is what reads a tenant's lease
in staging. This machine has no Tesseract, and a developer's machine may have version 4, which
reads differently — so the reader is exercised in the image itself. The build is cached by
Docker, so it costs seconds after the first run.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "tokelo-ocr-tests"


@pytest.fixture(scope="session")
def ocr_image() -> str:
    if not subprocess.run(["which", "docker"], capture_output=True).stdout:
        pytest.skip("docker isn't on PATH, so the reader can't be exercised")
    built = subprocess.run(
        ["docker", "build", "-f", "services/ocr/Dockerfile", "-t", IMAGE, "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr[-3000:]
    return IMAGE


@pytest.fixture(scope="session")
def reader(ocr_image: str) -> Callable[..., dict[str, Any]]:
    """Call the reader in the image: reader("photo", 1) or reader("count", "digital")."""

    def call(*arguments: object) -> dict[str, Any]:
        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                "-v",
                f"{ROOT / 'src' / 'tokelo'}:/function/tokelo:ro",
                "-v",
                f"{ROOT / 'tests' / 'fixtures' / 'leases'}:/fixtures:ro",
                "-v",
                f"{ROOT / 'tests' / 'ocr' / 'reader.py'}:/reader.py:ro",
                ocr_image,
                "/reader.py",
                *[str(a) for a in arguments],
            ],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr[-3000:]
        return json.loads(run.stdout)

    return call
