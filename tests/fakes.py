"""Stand-ins for what a worker talks to, shared by the lanes that talk to the same things.

The database is never faked: DynamoDB Local runs the conditional writes and the atomic counters
the workers' correctness rests on (tests/conftest.py). S3 is, because what matters about it in a
worker's test is only which objects are there, what they contain, and which version — and a
dictionary says that more clearly than a recording of the SDK would.
"""

import json
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

STORED_AT = datetime(2026, 9, 21, 8, 30, 0, tzinfo=UTC)


class Body:
    """What `get_object` hands back. boto3's StreamingBody reads whole or in chunks, and a worker
    that hashes a file reads it in chunks, so both are here."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            chunk, self._at = self._data[self._at :], len(self._data)
            return chunk
        chunk = self._data[self._at : self._at + size]
        self._at += len(chunk)
        return chunk


class Bucket:
    """S3, as far as a worker can tell: objects by key, each with a version and a time."""

    def __init__(self) -> None:
        # The latest version of each key, which is what a read without a version gets...
        self.objects: dict[str, bytes] = {}
        self.versions: dict[str, str] = {}
        self.modified: dict[str, datetime] = {}
        # ...and every version ever written, because the bucket is versioned: a later write
        # doesn't remove the one a digest was taken of (T039).
        self.history: dict[tuple[str, str], bytes] = {}

    def put(
        self, key: str, body: bytes, version: str = "v1", modified: datetime = STORED_AT
    ) -> None:
        self.objects[key] = body
        self.versions[key] = version
        self.modified[key] = modified
        self.history[(key, version)] = body

    def _find(self, key: str, version_id: str | None) -> bytes:
        if version_id:
            if (key, version_id) in self.history:
                return self.history[(key, version_id)]
        elif key in self.objects:
            return self.objects[key]
        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "GetObject",
        )

    # the calls the workers make, spelt as boto3 spells them
    def get_object(  # noqa: N803
        self, Bucket: str, Key: str, VersionId: str | None = None
    ) -> dict[str, Any]:
        return {"Body": Body(self._find(Key, VersionId))}

    def head_object(  # noqa: N803
        self, Bucket: str, Key: str, VersionId: str | None = None
    ) -> dict[str, Any]:
        data = self._find(Key, VersionId)
        return {
            "ContentLength": len(data),
            "LastModified": self.modified[Key],
            "VersionId": self.versions[Key],
        }

    def put_object(self, **call: Any) -> dict[str, Any]:
        """A new version of the key each time, as a versioned bucket makes, and its ID back. The
        body may be bytes or an open file, as boto3 takes either."""
        body = call["Body"]
        data = bytes(body) if isinstance(body, bytes | bytearray) else body.read()
        key = call["Key"]
        version = f"v{sum(1 for k, _ in self.history if k == key) + 1}"
        self.put(key, data, version=version)
        return {"VersionId": version}

    def page_jobs(self) -> list[str]:
        return sorted(k for k in self.objects if k.startswith("jobs/page/"))


def s3_record(
    key: str,
    *,
    bucket: str = "tokelo-test-documents-000000000000",
    receives: int = 1,
    message_id: str = "m1",
    version: str = "v1",
    size: int = 2048,
) -> dict[str, Any]:
    """One SQS record carrying an EventBridge `Object Created`, as Lambda delivers it."""
    return {
        "messageId": message_id,
        "body": json.dumps(
            {
                "detail-type": "Object Created",
                "source": "aws.s3",
                "detail": {
                    "bucket": {"name": bucket},
                    "object": {"key": key, "size": size, "version-id": version},
                },
            }
        ),
        "attributes": {"ApproximateReceiveCount": str(receives)},
        "eventSource": "aws:sqs",
    }


def batch(*records: dict[str, Any]) -> dict[str, Any]:
    return {"Records": list(records)}
