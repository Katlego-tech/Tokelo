"""Asking for a dossier, and following it to its download (docs/design/api.md §4 "A dossier
request", §6; REQ-013, REQ-001).

The `api` can't start the `dossier` worker itself: it is inside a VPC with no way out to SQS or
EventBridge (ADR-0003). What it can do is write an object to S3 through the gateway endpoint, and
EventBridge routes `jobs/dossier/*` to the worker's queue. So a request is four steps:
- check the selection ([selection.py](../dossier/selection.py)), so nothing the worker would have
  to refuse is ever queued
- record the `Dossier`, `requested`
- write the job object
- answer 202 with the dossier's ID, which the tenant follows with `GET /api/dossiers/{id}`

If the job object can't be written, the dossier is marked `failed` then and there and the answer
is a 503. No dossier waits for a job that was never written (api.md §4).

The download link names **the version the worker recorded**, so the digest the screen shows is
the digest of the file the link gives, whatever else was written to that key since (dossier.md
§4). It lasts five minutes, and each GET issues a fresh one.
"""

import json
import os
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from tokelo.api import storage, views
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core import keys
from tokelo.core.model import Dossier, DossierStatus
from tokelo.core.store import Store
from tokelo.dossier import selection

type Event = Mapping[str, Any]

JOB_VERSION = 1  # the job object's own version (api.md §6, "The dossier job request")
DOWNLOAD_LIFETIME = timedelta(minutes=5)  # api.md §6, "Download links"

NOT_STARTED = "This dossier couldn't be started. Please try again."

_ID = re.compile(rf"^{keys.UUID}$")

_store: Store | None = None
_s3: Any = None


def store_for() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def s3_for() -> Any:
    """One S3 client per container, signing as the browser needs it (storage.py)."""
    global _s3
    if _s3 is None:
        _s3 = storage.client()
    return _s3


def request_dossier(event: Event) -> Response:
    """POST /api/dossiers {document_ids} → 202 {dossier_id}."""
    tenant = tenant_of(event)
    store = store_for()
    try:
        wanted = selection.chosen(_body(event).get("document_ids"))
        # One query for all of them (domain-model.md §6, "a tenant's documents"), in the tenant's
        # own partition: another tenant's document is simply not in the answer (REQ-001).
        mine = {d.id: d for d in store.list_documents(tenant)}
        selection.check(wanted, mine)
    except selection.Refused as refusal:
        return error(422, "refused", str(refusal))

    dossier_id = str(uuid.uuid4())
    requested_at = _stamp(datetime.now(UTC))
    store.create_dossier(
        tenant,
        Dossier(
            id=dossier_id,
            status=DossierStatus.REQUESTED,
            document_ids=wanted,
            requested_at=requested_at,
        ),
    )

    job = {
        "version": JOB_VERSION,
        "dossier_id": dossier_id,
        "tenant_id": tenant,
        "document_ids": wanted,
        "requested_at": requested_at,
    }
    try:
        s3_for().put_object(
            Bucket=os.environ["TOKELO_DOCUMENTS_BUCKET"],
            Key=keys.dossier_job_key(dossier_id),
            Body=json.dumps(job).encode(),
            ContentType="application/json",
        )
    except ClientError, BotoCoreError:
        store.set_dossier_status(
            tenant, dossier_id, DossierStatus.FAILED, failure_reason=NOT_STARTED
        )
        return error(503, "not_started", NOT_STARTED)

    return json_response(202, {"dossier_id": dossier_id})


def get_dossier(event: Event, dossier_id: str) -> Response:
    """GET /api/dossiers/{id} → api.md §6's DossierView. Someone else's dossier is a 404, exactly
    as one that doesn't exist is (REQ-001)."""
    tenant = tenant_of(event)
    dossier = store_for().get_dossier(tenant, dossier_id) if _ID.match(dossier_id) else None
    if dossier is None:
        return error(404, "not_found", "No such dossier.")

    download_url: str | None = None
    expires_at: str | None = None
    if dossier.status is DossierStatus.READY and dossier.s3_key and dossier.s3_version_id:
        issued = datetime.now(UTC)
        download_url = s3_for().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": os.environ["TOKELO_DOCUMENTS_BUCKET"],
                "Key": dossier.s3_key,
                "VersionId": dossier.s3_version_id,
            },
            ExpiresIn=int(DOWNLOAD_LIFETIME.total_seconds()),
        )
        expires_at = _stamp(issued + DOWNLOAD_LIFETIME)

    return json_response(200, views.dossier_view(dossier, download_url, expires_at))


def _body(event: Event) -> dict[str, Any]:
    """The request's JSON object. Raises Refused, with what to tell the tenant."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as e:
        raise selection.Refused("The request isn't valid JSON.") from e
    if not isinstance(body, dict):
        raise selection.Refused("The request must be a JSON object.")
    return body


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
