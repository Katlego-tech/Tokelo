"""Deleting an account, and everything in it (REQ-016, REQ-011; docs/design/api.md §4 "Deleting
an account", docs/design/domain-model.md §3).

What is owed:
- **every file, every version of it:** the bucket is versioned, so deleting the current version
  alone would keep the evidence under a delete marker
- **every record** in the tenant's partition
- **the audit log, whole, and anonymous.** Its entries stay, with a last one for the deletion
  itself, but the row that mapped the pseudonym to the tenant is gone
- **nobody else's anything**

The store is DynamoDB Local; S3 is tests/fakes.py's versioned bucket.
"""

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from fakes import Bucket
from tokelo.core import keys, model
from tokelo.core.model import (
    AuditAction,
    Document,
    DocumentKind,
    DocumentStatus,
    Dossier,
    DossierStatus,
    TimelineEntry,
    TimelineSource,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
BUCKET = "tokelo-test-documents"


@pytest.fixture
def bucket() -> Bucket:
    return Bucket()


@pytest.fixture
def api(store, bucket, monkeypatch):
    from tokelo.api import account
    from tokelo.api.handler import handler

    monkeypatch.setenv("TOKELO_DOCUMENTS_BUCKET", BUCKET)
    monkeypatch.setattr(account, "store_for", lambda: store)
    monkeypatch.setattr(account, "s3_for", lambda: bucket)
    return handler


def delete(tenant: str | None = TENANT) -> dict:
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": "/api/account",
        "requestContext": {"http": {"method": "DELETE", "path": "/api/account"}},
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def a_tenant_with_everything(store, bucket: Bucket, tenant: str) -> str:
    """A tenant with a photo (two versions of it), a lease, a timeline entry, a dossier and its
    PDF, and an audit trail. Answers their pseudonym."""
    subject = store.create_tenant(tenant, created_at="2026-09-01T08:00:00Z")
    for n, kind in enumerate((DocumentKind.PHOTO, DocumentKind.LEASE)):
        document_id = f"{'ab'[n]}{tenant[1:]}"  # never the tenant's own ID
        key = keys.upload_key(tenant, kind, document_id)
        store.create_document(
            tenant,
            Document(
                id=document_id,
                kind=kind,
                status=DocumentStatus.REQUESTED,
                s3_key=key,
                content_type="image/jpeg",
                size_bytes=10,
                requested_at="2026-09-01T08:00:00Z",
            ),
        )
        bucket.put(key, b"first", version="v1")
        bucket.put(key, b"second", version="v2")
        store.append_audit(subject, AuditAction.UPLOAD, document_id, {"kind": str(kind)})
    store.add_timeline_entry(
        tenant,
        TimelineEntry(
            id="e1",
            occurred_at="2026-09-01T08:00:00Z",
            source=TimelineSource.CAPTURE,
            summary="Photograph taken",
            document_id=f"a{tenant[1:]}",
        ),
    )
    dossier_id = f"9{tenant[1:]}"
    store.create_dossier(
        tenant,
        Dossier(
            id=dossier_id,
            status=DossierStatus.REQUESTED,
            document_ids=[],
            requested_at="2026-09-02T08:00:00Z",
        ),
    )
    bucket.put(keys.dossier_key(tenant, dossier_id), b"%PDF", version="v1")
    return subject


def items_of(store, tenant: str) -> list[dict[str, Any]]:
    return store._query(model.tenant_pk(tenant), "")


def files_of(bucket: Bucket, tenant: str) -> list[tuple[str, str]]:
    return [
        (key, version)
        for (key, version) in bucket.history
        if key.startswith((f"uploads/{tenant}/", f"dossiers/{tenant}/"))
    ]


@pytest.mark.req("REQ-016")
def test_every_file_every_version_and_every_record_goes(api, store, bucket):
    a_tenant_with_everything(store, bucket, TENANT)
    assert files_of(bucket, TENANT) and items_of(store, TENANT)

    response = api(delete())

    assert response["statusCode"] == 202
    assert files_of(bucket, TENANT) == []
    assert items_of(store, TENANT) == []
    assert store.get_tenant(TENANT) is None


@pytest.mark.req("REQ-016", "REQ-011")
def test_the_audit_log_keeps_its_entries_and_none_can_be_traced_back(api, store, bucket):
    subject = a_tenant_with_everything(store, bucket, TENANT)

    api(delete())

    entries = store.list_audit(subject)
    assert [e.action for e in entries].count(AuditAction.UPLOAD) == 2
    (last,) = [e for e in entries if e.action is AuditAction.DELETE_ACCOUNT]
    # Three files (the photo, the lease and the dossier PDF), five versions between them; five
    # records (the row, two documents, the timeline entry, the dossier).
    assert last.detail == {"files": 3, "records": 5}
    # The only thing that mapped the pseudonym to the tenant was the tenant's row, now gone;
    # and nothing in the log names the tenant.
    assert store.get_tenant(TENANT) is None
    assert TENANT not in json.dumps([e.__dict__ for e in entries], default=str)


@pytest.mark.req("REQ-016", "REQ-001")
def test_nobody_elses_files_or_records_are_touched(api, store, bucket):
    a_tenant_with_everything(store, bucket, TENANT)
    a_tenant_with_everything(store, bucket, OTHER)
    theirs_files, theirs_items = files_of(bucket, OTHER), items_of(store, OTHER)

    api(delete())

    assert files_of(bucket, OTHER) == theirs_files
    assert items_of(store, OTHER) == theirs_items


@pytest.mark.req("REQ-016")
def test_deleting_again_finds_nothing_and_still_answers_202(api, store, bucket):
    a_tenant_with_everything(store, bucket, TENANT)
    api(delete())

    assert api(delete())["statusCode"] == 202


class Refusing(Bucket):
    def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObjects")


@pytest.mark.req("REQ-016")
def test_if_the_files_cant_go_the_records_stay_so_it_can_be_tried_again(api, store, monkeypatch):
    """api.md §4: files before records. A failure leaves the records saying what is stored."""
    from tokelo.api import account

    refusing = Refusing()
    monkeypatch.setattr(account, "s3_for", lambda: refusing)
    a_tenant_with_everything(store, refusing, TENANT)

    with pytest.raises(ClientError):
        api(delete())

    assert items_of(store, TENANT)
    assert store.get_tenant(TENANT) is not None


class PartlyRefusing(Bucket):
    def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        first, *rest = Delete["Objects"]
        super().delete_objects(Bucket=Bucket, Delete={"Objects": rest})
        return {"Errors": [{"Key": first["Key"], "Code": "AccessDenied", "Message": "no"}]}


@pytest.mark.req("REQ-016")
def test_a_file_s3_refuses_to_delete_stops_the_deletion_before_the_records(api, store, monkeypatch):
    """DeleteObjects answers 200 even when it refuses some objects, and says so in `Errors`."""
    from tokelo.api import account

    partly = PartlyRefusing()
    monkeypatch.setattr(account, "s3_for", lambda: partly)
    a_tenant_with_everything(store, partly, TENANT)

    with pytest.raises(RuntimeError, match="couldn't be deleted"):
        api(delete())

    assert store.get_tenant(TENANT) is not None


@pytest.mark.req("REQ-001")
def test_an_unauthenticated_request_deletes_nothing(api, store, bucket):
    a_tenant_with_everything(store, bucket, TENANT)

    assert api(delete(tenant=None))["statusCode"] == 401
    assert items_of(store, TENANT)
