"""Jobs, from the object in S3 to the worker that does them, and into the dead-letter queue when
they can't be done (REQ-017; docs/design/infrastructure.md §4, domain-model.md §4).

The events here are the shapes AWS actually sends: an SQS record whose body is the EventBridge
event whose detail is S3's. The marking of a failed document runs against DynamoDB Local, because
"the tenant sees a failed item as failed" is the point of the task."""

import json

import pytest

from tokelo.core import jobs, keys
from tokelo.core.model import Document, DocumentKind, DocumentStatus

TENANT = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "33333333-3333-4333-8333-333333333333"
BUCKET = "tokelo-test-documents-000000000000"


def s3_record(key: str, *, receives: int = 1, message_id: str = "m1", size: int = 2048) -> dict:
    """One SQS record, as a Lambda event source mapping delivers it."""
    return {
        "messageId": message_id,
        "receiptHandle": "AQEB…",
        "body": json.dumps(
            {
                "version": "0",
                "id": "5f6e7d8c",
                "detail-type": "Object Created",
                "source": "aws.s3",
                "time": "2026-09-20T06:01:00Z",
                "region": "eu-west-1",
                "detail": {
                    "version": "0",
                    "bucket": {"name": BUCKET},
                    "object": {"key": key, "size": size, "version-id": "v1", "etag": "e"},
                    "reason": "PutObject",
                },
            }
        ),
        "attributes": {"ApproximateReceiveCount": str(receives)},
        "eventSource": "aws:sqs",
        "awsRegion": "eu-west-1",
    }


def an_upload(kind: DocumentKind = DocumentKind.LEASE) -> Document:
    return Document(
        id=DOCUMENT,
        kind=kind,
        status=DocumentStatus.REQUESTED,
        s3_key=keys.upload_key(TENANT, kind, DOCUMENT),
        content_type="application/pdf",
        size_bytes=2048,
        requested_at="2026-09-20T06:00:00Z",
    )


@pytest.mark.req("REQ-017")
def test_an_object_becomes_a_job_that_names_its_tenant_and_document():
    key = keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT)
    (job,) = jobs.of({"Records": [s3_record(key)]})

    assert job.bucket == BUCKET
    assert job.key == key
    assert job.version_id == "v1"
    assert job.size == 2048
    assert job.tenant_id == TENANT
    assert job.document_id == DOCUMENT
    assert job.kind is DocumentKind.LEASE
    assert job.last_try is False


@pytest.mark.req("REQ-017")
def test_a_job_object_names_the_document_it_is_for():
    (page,) = jobs.of({"Records": [s3_record(keys.page_job_key(DOCUMENT, 3))]})
    assert page.document_id == DOCUMENT and page.tenant_id is None and page.kind is None

    (dossier,) = jobs.of({"Records": [s3_record(keys.dossier_job_key(DOCUMENT))]})
    assert dossier.document_id == DOCUMENT


@pytest.mark.req("REQ-017")
def test_a_key_the_project_never_writes_is_refused_rather_than_guessed():
    for key in ("uploads/not-a-uuid/lease/x", "somewhere/else.txt", "uploads/", ""):
        with pytest.raises(jobs.NotAJob):
            jobs.of({"Records": [s3_record(key)]})


@pytest.mark.req("REQ-017")
def test_the_work_runs_once_per_message_and_says_nothing_when_it_all_works(store):
    store.create_document(TENANT, an_upload())
    done: list[str] = []

    answer = jobs.run(
        {"Records": [s3_record(keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT), size=10)]},
        lambda job: done.append(job.key),
        store=store,
    )

    assert done == [keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT)]
    assert answer == {"batchItemFailures": []}  # nothing to retry


@pytest.mark.req("REQ-017")
def test_a_job_that_fails_is_reported_for_retry_and_the_document_is_left_alone(store):
    store.create_document(TENANT, an_upload())

    def fails(job: jobs.Job) -> None:
        raise RuntimeError("the page reader fell over")

    answer = jobs.run(
        {"Records": [s3_record(keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT))]},
        fails,
        store=store,
    )

    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    # Two tries are still to come, so the tenant is not told it failed yet.
    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None and stored.document.status is DocumentStatus.REQUESTED


@pytest.mark.req("REQ-017")
def test_the_third_failure_marks_the_document_failed_and_still_goes_to_the_dead_letter_queue(store):
    store.create_document(TENANT, an_upload())

    def fails(job: jobs.Job) -> None:
        assert job.last_try is True  # the worker can tell this is the last go
        raise RuntimeError("the page reader fell over again")

    answer = jobs.run(
        {"Records": [s3_record(keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT), receives=3)]},
        fails,
        store=store,
    )

    # Still reported as failed, so SQS moves it to the dead-letter queue where the alarm is.
    assert answer == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    stored = store.get_document(TENANT, DOCUMENT)
    assert stored is not None
    assert stored.document.status is DocumentStatus.FAILED
    assert stored.document.failure_reason
    assert "fell over" not in stored.document.failure_reason  # the tenant gets words, not a stack


@pytest.mark.req("REQ-017")
def test_one_bad_message_in_a_batch_doesnt_take_the_good_ones_with_it(store):
    store.create_document(TENANT, an_upload())
    key = keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT)
    done: list[str] = []

    def work(job: jobs.Job) -> None:
        if job.message_id == "bad":
            raise RuntimeError("nope")
        done.append(job.message_id)

    answer = jobs.run(
        {
            "Records": [
                s3_record(key, message_id="good-1"),
                s3_record(key, message_id="bad"),
                s3_record(key, message_id="good-2"),
            ]
        },
        work,
        store=store,
    )

    assert done == ["good-1", "good-2"]
    assert answer == {"batchItemFailures": [{"itemIdentifier": "bad"}]}


@pytest.mark.req("REQ-017")
def test_a_job_for_a_document_that_is_gone_is_done_with_not_retried_forever(store):
    """The tenant deleted their account between the upload and the job (REQ-016). There is
    nothing to work on and nothing to mark, and retrying it three times helps nobody."""
    answer = jobs.run(
        {"Records": [s3_record(keys.upload_key(TENANT, DocumentKind.LEASE, DOCUMENT))]},
        lambda job: (_ for _ in ()).throw(jobs.Gone("the document was deleted")),
        store=store,
    )
    assert answer == {"batchItemFailures": []}
