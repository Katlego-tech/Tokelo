"""Asking for a dossier, and following it to its download (REQ-013, REQ-001; docs/design/api.md
§4 "A dossier request", §6).

A dossier is built by the `dossier` worker, which the `api` can't call: there is no way out of
the VPC to SQS (ADR-0003). So the request is an object in S3, and what is checked here is
everything the `api` owes before that object exists:
- a selection it can honour: something chosen, at most 150 documents, every one the tenant's and
  finished
- the `Dossier` item, `requested`
- the job object, in api.md §6's shape, at the key EventBridge routes to the `dossier` queue

What comes back afterwards is `DossierView`, with a download link that names the version the
worker recorded.

The store is DynamoDB Local. S3 is tests/fakes.py's bucket, plus a real boto3 client for signing
the download link. Signing is local arithmetic, so no call leaves the test.
"""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.exceptions import ClientError

from fakes import Bucket, s3_record
from tokelo.core import jobs, keys
from tokelo.core.model import (
    Document,
    DocumentKind,
    DocumentStatus,
    Dossier,
    DossierStatus,
    LeaseStatus,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
BUCKET = "tokelo-staging-documents"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class S3(Bucket):
    """The fake bucket, signing as the `api`'s real client does (api/storage.py). Signing is
    local arithmetic: the link is made here and never fetched."""

    def __init__(self) -> None:
        from tokelo.api import storage

        super().__init__()
        self._signer: Any = storage.client()

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        return self._signer.generate_presigned_url(*args, **kwargs)


class Unwritable(S3):
    """A bucket that refuses the job object: the gateway endpoint down, or a policy mistake. It
    remembers the key it refused, which names the dossier."""

    refused: str = ""

    def put_object(self, **call: Any) -> dict[str, Any]:
        self.refused = call["Key"]
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject")


@pytest.fixture
def bucket(store) -> S3:
    """After `store`, which sets the environment a function would be given."""
    return S3()


@pytest.fixture
def api(store, bucket, monkeypatch):
    from tokelo.api import dossiers
    from tokelo.api.handler import handler

    monkeypatch.setenv("TOKELO_DOCUMENTS_BUCKET", BUCKET)
    monkeypatch.setattr(dossiers, "store_for", lambda: store)
    monkeypatch.setattr(dossiers, "s3_for", lambda: bucket)
    return handler


def request(method: str, path: str, body: Any = None, tenant: str | None = TENANT) -> dict:
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "body": body if isinstance(body, str) or body is None else json.dumps(body),
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def ask(document_ids: Any, tenant: str = TENANT) -> dict:
    return request("POST", "/api/dossiers", {"document_ids": document_ids}, tenant)


def body_of(response: dict) -> dict:
    return json.loads(response["body"])


def refusal(response: dict) -> str:
    assert response["statusCode"] == 422, response
    return body_of(response)["error"]["message"]


@pytest.fixture
def uploaded(store):
    """A document of `kind`, left in the state named: `finished` as its worker leaves it
    (`processed`, and a lease's reading `analysed`), or somewhere short of that."""

    def make(kind: DocumentKind, state: str = "finished", tenant: str = TENANT) -> str:
        document_id = str(uuid.uuid4())
        store.create_document(
            tenant,
            Document(
                id=document_id,
                kind=kind,
                status=DocumentStatus.REQUESTED,
                s3_key=keys.upload_key(tenant, kind, document_id),
                content_type="application/pdf",
                size_bytes=2048,
                requested_at="2026-09-21T08:00:00Z",
            ),
        )
        if state == "requested":
            return document_id
        if state == "expired":
            store.set_document_status(tenant, document_id, DocumentStatus.EXPIRED)
            return document_id
        store.record_stored(tenant, document_id, "v1", "ab" * 32, "2026-09-21T08:30:00Z")
        if state == "failed":
            store.set_document_status(
                tenant, document_id, DocumentStatus.FAILED, failure_reason="nope"
            )
            return document_id
        if kind is DocumentKind.LEASE:
            # As the ocr worker leaves it: the reading `analysed` and the document `processed`
            # together (ocr/flags.py), or two pages of four still to come.
            reading = LeaseStatus.ANALYSED if state == "finished" else LeaseStatus.READING
            store.set_lease(tenant, document_id, 4, 4 if state == "finished" else 2, reading)
        if state == "finished":
            store.set_document_status(tenant, document_id, DocumentStatus.PROCESSED)
        return document_id

    return make


# ------------------------------------------------------------ the request ---
@pytest.mark.req("REQ-013")
def test_a_selection_of_finished_documents_becomes_a_requested_dossier_and_its_job(
    api, store, bucket, uploaded
):
    chosen = [
        uploaded(DocumentKind.LEASE),
        uploaded(DocumentKind.PHOTO),
        uploaded(DocumentKind.NOTICE),
        uploaded(DocumentKind.CHAT),
    ]

    response = api(ask(chosen))

    assert response["statusCode"] == 202
    answer = body_of(response)
    assert set(answer) == {"dossier_id"}
    dossier_id = answer["dossier_id"]

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None
    assert dossier.status is DossierStatus.REQUESTED
    assert dossier.document_ids == chosen
    assert STAMP.match(dossier.requested_at)

    # api.md §6's job request, exactly: what the worker is told, and nothing more.
    job = json.loads(bucket.objects[keys.dossier_job_key(dossier_id)])
    assert job == {
        "version": 1,
        "dossier_id": dossier_id,
        "tenant_id": TENANT,
        "document_ids": chosen,
        "requested_at": dossier.requested_at,
    }


@pytest.mark.req("REQ-013")
def test_the_job_is_written_where_the_dossier_queue_takes_it_from(api, bucket, uploaded):
    """EventBridge routes `jobs/dossier/*` to the `dossier` queue (infra/modules/tokelo-env/
    events.tf), and the worker reads the key back as a dossier job. That's the whole path from
    the request to the queue, since the `api` can't reach SQS itself (ADR-0003)."""
    dossier_id = body_of(api(ask([uploaded(DocumentKind.PHOTO)])))["dossier_id"]

    (written,) = [k for k in bucket.objects if k.startswith("jobs/")]
    assert written == f"jobs/dossier/{dossier_id}.json"
    (job,) = jobs.of({"Records": [s3_record(written)]})
    assert job.document_id == dossier_id and job.tenant_id is None


@pytest.mark.req("REQ-013")
def test_nothing_selected_is_refused_and_says_why(api, store, bucket):
    """SPEC.md US3, "nothing selected": Tokelo refuses, and says why."""
    message = refusal(api(ask([])))

    assert "Nothing is selected" in message
    assert bucket.objects == {}


@pytest.mark.req("REQ-013")
def test_more_than_150_documents_is_refused_before_anything_is_looked_up(api, bucket):
    message = refusal(api(ask([str(uuid.uuid4()) for _ in range(151)])))

    assert "at most 150" in message and "151" in message
    assert bucket.objects == {}


@pytest.mark.req("REQ-013")
def test_150_documents_is_not_too_many(api, uploaded):
    chosen = [uploaded(DocumentKind.PHOTO) for _ in range(150)]

    assert api(ask(chosen))["statusCode"] == 202


@pytest.mark.req("REQ-013")
def test_the_same_document_chosen_twice_is_in_the_dossier_once(api, store, uploaded):
    photo, notice = uploaded(DocumentKind.PHOTO), uploaded(DocumentKind.NOTICE)

    dossier_id = body_of(api(ask([photo, notice, photo])))["dossier_id"]

    dossier = store.get_dossier(TENANT, dossier_id)
    assert dossier is not None and dossier.document_ids == [photo, notice]


@pytest.mark.req("REQ-001")
def test_another_tenants_document_is_refused_exactly_like_one_that_doesnt_exist(
    api, store, bucket, uploaded
):
    """The same words either way: telling them apart would confirm that the other tenant's
    document exists (api.md §8)."""
    mine = uploaded(DocumentKind.PHOTO)
    theirs = uploaded(DocumentKind.PHOTO, tenant=OTHER)

    foreign = refusal(api(ask([mine, theirs])))
    missing = refusal(api(ask([mine, str(uuid.uuid4())])))

    assert foreign == missing
    assert "isn't one of yours" in foreign
    assert bucket.objects == {}


@pytest.mark.req("REQ-013")
@pytest.mark.parametrize(
    ("kind", "state", "said"),
    [
        (DocumentKind.LEASE, "reading", "still being read"),
        (DocumentKind.PHOTO, "stored", "still being read"),
        (DocumentKind.CHAT, "failed", "couldn't be processed"),
        (DocumentKind.NOTICE, "requested", "was never uploaded"),
        (DocumentKind.PHOTO, "expired", "was never uploaded"),
    ],
)
def test_a_document_that_isnt_finished_is_refused_with_the_reason(
    api, store, bucket, uploaded, kind, state, said
):
    """api.md §6, "What a dossier may hold": half a lease's flags, or half an export's messages,
    in a PDF that looks complete would be worse than no dossier."""
    message = refusal(api(ask([uploaded(DocumentKind.PHOTO), uploaded(kind, state)])))

    assert said in message
    assert bucket.objects == {}


@pytest.mark.req("REQ-001")
def test_an_id_that_isnt_a_uuid_is_refused_before_the_store_is_asked(api, bucket, uploaded):
    """Every ID this project issues is a UUID. A prefix of a real one must not select it: the
    store reads a document by the start of its sort key (domain-model.md §6)."""
    real = uploaded(DocumentKind.PHOTO)

    message = refusal(api(ask([real[:8]])))

    assert "isn't one of yours" in message
    assert bucket.objects == {}


@pytest.mark.req("REQ-013")
@pytest.mark.parametrize(
    "body",
    [
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({}),
        json.dumps({"document_ids": "one"}),
        json.dumps({"document_ids": [1, 2]}),
    ],
)
def test_a_malformed_request_is_refused(api, bucket, body):
    response = api(request("POST", "/api/dossiers", body))

    assert response["statusCode"] == 422
    assert body_of(response)["error"]["code"] == "refused"
    assert bucket.objects == {}


@pytest.mark.req("REQ-013")
def test_a_job_that_cant_be_written_fails_the_dossier_and_answers_503(
    api, store, uploaded, monkeypatch
):
    """api.md §4: no dossier waits for a job that was never written."""
    from tokelo.api import dossiers

    unwritable = Unwritable()
    monkeypatch.setattr(dossiers, "s3_for", lambda: unwritable)

    response = api(ask([uploaded(DocumentKind.PHOTO)]))

    assert response["statusCode"] == 503
    parsed = keys.parse(unwritable.refused)
    assert parsed is not None and parsed.document_id is not None
    dossier = store.get_dossier(TENANT, parsed.document_id)
    assert dossier is not None and dossier.status is DossierStatus.FAILED
    assert dossier.failure_reason == "This dossier couldn't be started. Please try again."


@pytest.mark.req("REQ-001")
def test_an_unauthenticated_request_is_refused(api):
    assert (
        api(request("POST", "/api/dossiers", {"document_ids": []}, tenant=None))["statusCode"]
        == 401
    )


# --------------------------------------------------------------- the view ---
def follow(dossier_id: str, tenant: str = TENANT) -> dict:
    return request("GET", f"/api/dossiers/{dossier_id}", tenant=tenant)


def a_dossier(
    store,
    status: DossierStatus = DossierStatus.REQUESTED,
    failure_reason: str | None = None,
) -> str:
    dossier_id = str(uuid.uuid4())
    store.create_dossier(
        TENANT,
        Dossier(
            id=dossier_id,
            status=status,
            document_ids=[str(uuid.uuid4())],
            requested_at="2026-10-01T09:00:00Z",
            failure_reason=failure_reason,
        ),
    )
    return dossier_id


VIEW = {
    "id",
    "status",
    "requested_at",
    "page_count",
    "size_bytes",
    "sha256",
    "failure_reason",
    "download_url",
    "expires_at",
}


@pytest.mark.req("REQ-013")
def test_a_dossier_being_built_says_so_and_offers_no_link(api, store):
    dossier_id = a_dossier(store, status=DossierStatus.COMPILING)

    response = api(follow(dossier_id))

    assert response["statusCode"] == 200
    view = body_of(response)
    assert set(view) == VIEW
    assert view["id"] == dossier_id
    assert view["status"] == "compiling"
    assert view["requested_at"] == "2026-10-01T09:00:00Z"
    for absent in VIEW - {"id", "status", "requested_at"}:
        assert view[absent] is None, absent


@pytest.mark.req("REQ-013")
def test_a_ready_dossier_links_to_the_version_the_worker_recorded_for_5_minutes(api, store):
    """api.md §6, "Download links": the digest on the screen is the digest of the file the link
    gives, because the link names the version that digest was recorded with."""
    dossier_id = str(uuid.uuid4())
    key = keys.dossier_key(TENANT, dossier_id)
    a_ready = {
        "status": DossierStatus.READY,
        "s3_key": key,
        "s3_version_id": "v7",
        "sha256": "51c2" + "0" * 56 + "a9e4",
        "page_count": 38,
        "size_bytes": 9_646_899,
        "ready_at": "2026-10-01T09:01:30Z",
    }
    store.create_dossier(
        TENANT,
        Dossier(
            id=dossier_id,
            document_ids=[str(uuid.uuid4())],
            requested_at="2026-10-01T09:00:00Z",
            **a_ready,
        ),
    )
    before = datetime.now(UTC).replace(microsecond=0)

    view = body_of(api(follow(dossier_id)))

    assert view["status"] == "ready"
    assert view["page_count"] == 38
    assert view["size_bytes"] == 9_646_899
    assert view["sha256"] == a_ready["sha256"]
    assert view["failure_reason"] is None

    link = urlparse(view["download_url"])
    query = parse_qs(link.query)
    assert f"{link.scheme}://{link.hostname}" == f"https://{BUCKET}.s3.eu-west-1.amazonaws.com"
    assert link.path == f"/{key}"
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["versionId"] == ["v7"]
    assert query["X-Amz-Expires"] == ["300"]

    expires = datetime.strptime(view["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before + timedelta(minutes=5) <= expires <= before + timedelta(minutes=5, seconds=5)


@pytest.mark.req("REQ-013")
def test_a_failed_dossier_says_why(api, store):
    dossier_id = a_dossier(
        store, status=DossierStatus.FAILED, failure_reason="Too many records for one dossier."
    )

    view = body_of(api(follow(dossier_id)))

    assert view["status"] == "failed"
    assert view["failure_reason"] == "Too many records for one dossier."
    assert view["download_url"] is None


@pytest.mark.req("REQ-001")
def test_someone_elses_dossier_is_a_404(api, store):
    dossier_id = a_dossier(store)

    assert api(follow(dossier_id, tenant=OTHER))["statusCode"] == 404
    assert api(follow(str(uuid.uuid4())))["statusCode"] == 404
