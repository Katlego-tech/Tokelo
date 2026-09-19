"""The `ocr` worker's entry point (docs/design/ocr.md §7)."""

from collections.abc import Mapping
from typing import Any

from tokelo.core.health import is_health_check, unknown


def handler(event: Mapping[str, Any], context: object = None) -> dict[str, Any]:
    if is_health_check(event):
        return {"ok": True}
    raise unknown(event, "ocr")
