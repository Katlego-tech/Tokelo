"""Deleting an account, and everything in it (docs/design/api.md §4 "Deleting an account";
REQ-016, REQ-011).

The order is the design's, and each step is where it is for a reason:
1. **The pseudonym, read first.** The tenant's row is the only link between the tenant and
   their audit entries, and it is about to go.
2. **The files: every version, and every delete marker,** under `uploads/{tenant}/` and
   `dossiers/{tenant}/`. The bucket is versioned, so deleting only the current version would
   keep the evidence, hidden under a marker. This comes before the records: if a file can't be
   deleted, the call fails and the records still say what is stored.
3. **The records:** the tenant's whole partition, their row with it (`Store.delete_tenant`).
4. **An audit entry,** under the pseudonym that now maps to nobody: how many files and records
   went. The audit log keeps every entry, and none of them can be traced back.

Calling it again finds nothing and answers 202, so a tenant whose sign-in account couldn't be
deleted afterwards (the web app does that, with their own token) can simply try again.
"""

import os
from collections.abc import Mapping
from typing import Any

from tokelo.api import storage
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, json_response
from tokelo.core.model import AuditAction
from tokelo.core.store import Store

type Event = Mapping[str, Any]

BATCH = 1000  # the most DeleteObjects takes at once

_store: Store | None = None
_s3: Any = None


def store_for() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def s3_for() -> Any:
    """One S3 client per container, configured as the rest of the api's (storage.py)."""
    global _s3
    if _s3 is None:
        _s3 = storage.client()
    return _s3


def delete_account(event: Event) -> Response:
    """DELETE /api/account → 202."""
    tenant = tenant_of(event)
    store = store_for()
    row = store.get_tenant(tenant)
    subject = row["audit_subject"] if row else None

    bucket = os.environ["TOKELO_DOCUMENTS_BUCKET"]
    files = sum(
        delete_prefix(s3_for(), bucket, prefix)
        for prefix in (f"uploads/{tenant}/", f"dossiers/{tenant}/")
    )
    records = store.delete_tenant(tenant)

    if subject is not None:
        store.append_audit(
            subject, AuditAction.DELETE_ACCOUNT, "account", {"files": files, "records": records}
        )
    return json_response(202, {})


def delete_prefix(s3: Any, bucket: str, prefix: str) -> int:
    """Every version and delete marker under `prefix`, deleted; answers how many objects there
    were (a file with three versions is one). Raises if S3 refuses any of them."""
    deleted_keys: set[str] = set()
    marker: dict[str, str] = {}
    while True:
        page = s3.list_object_versions(Bucket=bucket, Prefix=prefix, **marker)
        targets = [
            {"Key": v["Key"], "VersionId": v["VersionId"]}
            for v in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
        ]
        for start in range(0, len(targets), BATCH):
            chunk = targets[start : start + BATCH]
            answer = s3.delete_objects(Bucket=bucket, Delete={"Objects": chunk, "Quiet": True})
            # DeleteObjects answers 200 even when it refuses some objects: they are in Errors.
            if refused := answer.get("Errors"):
                raise RuntimeError(
                    f"{len(refused)} file version(s) under {prefix} couldn't be deleted: "
                    f"{refused[0].get('Code')}"
                )
        deleted_keys.update(t["Key"] for t in targets)
        if not page.get("IsTruncated"):
            return len(deleted_keys)
        marker = {
            "KeyMarker": page["NextKeyMarker"],
            "VersionIdMarker": page["NextVersionIdMarker"],
        }
