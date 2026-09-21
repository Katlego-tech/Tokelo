"""Pre-signed uploads (docs/design/api.md §4, §6; REQ-002, REQ-003, NFR-006).

A file's bytes never pass through this function. The tenant asks for permission to write one
object; what they get back is a POST policy S3 itself enforces — one key, one content type, a
size range and a quarter of an hour. The `api` keeps no copy, holds no buffer and has no
`PutObject` permission on anything but the `uploads/` prefix (infrastructure.md §6).

The limits are checked here, when the URL is asked for, so a file this project can't use is
refused before it is uploaded rather than after. They are read from `ocr/intake.py`, which is
also where the worker reads them: it checks again, against the bytes, what only it can see — the
file's real type and a PDF's page count, neither of which a policy can look at (REQ-003).
"""

import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core.keys import upload_key
from tokelo.core.model import Document, DocumentKind, DocumentStatus
from tokelo.core.store import Store
from tokelo.ocr.intake import KINDS, MEGABYTE, Refused, one_of

type Event = Mapping[str, Any]

LIFETIME = timedelta(minutes=15)  # NFR-006: the URL is short-lived, whatever else changes

_store: Store | None = None
_s3: Any = None


def store_for() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def s3_for() -> Any:
    """One S3 client per container. boto3 ships no types; this is the only line that knows."""
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def asked_for(event: Event) -> tuple[DocumentKind, str, int]:
    """The request, checked (REQ-003). Raises Refused, with what to tell the tenant."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as e:
        raise Refused("The request isn't valid JSON.") from e
    if not isinstance(body, dict):
        raise Refused("The request must be a JSON object.")

    try:
        kind = DocumentKind(str(body.get("kind", "")))
    except ValueError as e:
        raise Refused(
            f"'{body.get('kind')}' isn't a kind this project takes: "
            f"it has to be {one_of([str(k) for k in KINDS])}."
        ) from e

    limits = KINDS[kind]
    content_type = str(body.get("content_type", ""))
    if content_type not in limits.types:
        named = f"the content type {content_type}" if content_type else "no content type"
        raise Refused(f"A {kind} with {named}: it has to be {one_of(sorted(limits.types))}.")

    size = body.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise Refused("An upload needs its size in bytes, and an empty file is no use.")
    if size > limits.size:
        raise Refused(f"A {kind} may be at most {limits.size // MEGABYTE} MB.")

    # `filename` is in the request and is deliberately not kept: a file's name is the tenant's
    # (and often their landlord's) and the system has no use for it. The key is the document's ID.
    return kind, content_type, size


def request_upload(event: Event) -> Response:
    """POST /api/uploads: record the document, and sign the permission to write it once."""
    tenant = tenant_of(event)
    try:
        kind, content_type, size = asked_for(event)
    except Refused as refusal:
        return error(422, "refused", str(refusal))

    document_id = str(uuid.uuid4())
    key = upload_key(tenant, kind, document_id)
    now = datetime.now(UTC)
    expires_at = now + LIFETIME

    store_for().create_document(
        tenant,
        Document(
            id=document_id,
            kind=kind,
            status=DocumentStatus.REQUESTED,
            s3_key=key,
            content_type=content_type,
            size_bytes=size,
            requested_at=_stamp(now),
        ),
    )

    # The conditions are the permission: that exact key, that exact type, and a size from one
    # byte to the kind's limit. S3 refuses anything else, so a browser that is tricked into
    # posting somewhere or something else gets nowhere (api.md §Threats).
    signed = s3_for().generate_presigned_post(
        Bucket=os.environ["TOKELO_DOCUMENTS_BUCKET"],
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"key": key},
            {"Content-Type": content_type},
            ["content-length-range", 1, KINDS[kind].size],
        ],
        ExpiresIn=int(LIFETIME.total_seconds()),
    )

    return json_response(
        201,
        {
            "document_id": document_id,
            "url": signed["url"],
            "fields": signed["fields"],
            "expires_at": _stamp(expires_at),
        },
    )


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
