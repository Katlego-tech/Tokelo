"""Verifying that an evidence file is unchanged (docs/design/api.md §6, docs/design/evidence.md
§4; REQ-010, REQ-011).

The `evidence` worker recorded a digest of the file when it was stored (T037). This endpoint takes
it again and says whether the two agree. What makes the answer worth anything is where the bytes
come from:

* **The stored object, by the recorded version.** Never a file the client sends, and never
  whatever happens to be at the key now: the bucket is versioned, so an edited photo uploaded
  over the original is a new version, and the one the digest was taken of is still the one read.
* **Hashed here, by the same code the worker used** ([digest.py](../evidence/digest.py)).

Every verification is an audit entry, under the tenant's pseudonym, whatever it found (REQ-011).
A file that is someone else's, a lease, or no file at all is the same 404 (REQ-001).
"""

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from tokelo.api import views
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core.model import AuditAction, DocumentKind
from tokelo.core.store import Store
from tokelo.evidence import digest

type Event = Mapping[str, Any]

# REQ-010's "evidence file": what the `evidence` worker fingerprints. A lease is read and checked
# by the `ocr` worker instead, and isn't kept as evidence.
EVIDENCE = (DocumentKind.PHOTO, DocumentKind.NOTICE, DocumentKind.CHAT)

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


def verify(event: Event, document_id: str) -> Response:
    """POST /api/evidence/{id}/verify."""
    tenant = tenant_of(event)
    store = store_for()
    stored = store.get_document(tenant, document_id)
    if stored is None or stored.document.kind not in EVIDENCE:
        return error(404, "not_found", "No such evidence file.")

    document = stored.document
    if not document.sha256 or not document.s3_version_id:
        return error(409, "not_stored", "This file hasn't been stored and fingerprinted yet.")

    try:
        computed = digest.sha256_of(
            s3_for(),
            os.environ["TOKELO_DOCUMENTS_BUCKET"],
            document.s3_key,
            document.s3_version_id,
        )
    except ClientError as e:
        # The version the digest belongs to can't be read, so there is nothing to compare, and
        # "matches" must never be said of nothing.
        if e.response["Error"]["Code"] in digest.MISSING:
            return error(404, "not_found", "This file is no longer stored.")
        raise

    verified_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    answer = views.verification(document.sha256, computed, verified_at)
    # The tenant's row holds the pseudonym the entry is filed under; on a first request it is made
    # here (api.md §4), and on any other this answers the one already there.
    subject = store.create_tenant(tenant, created_at=verified_at)
    store.append_audit(
        subject,
        AuditAction.VERIFY,
        document_id,
        {
            "matches": answer["matches"],
            "recorded_sha256": answer["recorded_sha256"],
            "computed_sha256": answer["computed_sha256"],
        },
        at=verified_at,
    )
    return json_response(200, answer)
