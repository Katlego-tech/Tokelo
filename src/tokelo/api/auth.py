"""Who is asking (docs/design/api.md §4).

API Gateway's JWT authorizer checks the token — the user pool as issuer, the web app's client as
audience, and the expiry — before a request reaches this function, so what arrives here is a
claim that has already been verified (infrastructure.md §6). This module is the one place that
reads it, and the only place a tenant ID comes from.

It checks again that the claim is there. API Gateway refusing the request is the wall; this is
the lock behind it, and it costs one dictionary lookup: a route accidentally left open, or moved
out from behind the authorizer, must not serve anybody's records."""

from collections.abc import Mapping
from typing import Any

type Event = Mapping[str, Any]


class Unauthenticated(Exception):
    """No verified claim on the request, so there is no tenant to serve."""


def tenant_of(event: Event) -> str:
    """The tenant's ID: the Cognito user's `sub`, which is also their partition key
    (domain-model.md §3). Raises Unauthenticated when the request carries no verified claim."""
    context = event.get("requestContext", {})
    claims = context.get("authorizer", {}).get("jwt", {}).get("claims", {})
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise Unauthenticated
    return subject
