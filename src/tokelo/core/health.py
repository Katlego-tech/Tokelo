"""What every worker shares before its own jobs exist: the kit's health contract, and refusing an
event it doesn't know (docs/design/infrastructure.md §4)."""

from collections.abc import Mapping
from typing import Any

HEALTH_EVENT = {"realm": "health"}


class UnknownEvent(ValueError):
    """An invocation this function has no handling for. Raised, never swallowed: Lambda records
    it as a failed invocation, and an SQS job goes back to its queue, then to its dead-letter
    queue."""


def is_health_check(event: Mapping[str, Any]) -> bool:
    return dict(event) == HEALTH_EVENT


def unknown(event: Mapping[str, Any], worker: str) -> UnknownEvent:
    keys = ", ".join(sorted(event)) or "none"
    return UnknownEvent(f"the {worker} worker doesn't handle this event (its keys: {keys})")
