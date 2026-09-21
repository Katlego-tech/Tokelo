"""Fingerprinting a stored object (REQ-008; docs/design/evidence.md §4).

A tenant's photograph is worth something at a Tribunal only if it can be shown to be the file
that was uploaded, and not one edited since. Everything that rests on that rests on this module,
so it has one rule: **the digest is taken from the stored object, by version, and from nothing
else.** Not from a header the browser sent, not from the size on the upload request, not from
anything a client could choose.

Two smaller decisions follow from the same thought.

**The time is the object's, not the worker's.** S3 records when it took the file; this worker may
run minutes later, or hours later after a redrive, and a timestamp it made up would date the
evidence to when the queue got round to it.

**The bytes are read a chunk at a time.** A 20 MB photograph on a 512 MB function, several at
once, must not be held whole to be hashed — and a digest doesn't need it to be.
"""

import hashlib
from dataclasses import dataclass
from typing import Any

# Big enough that a 20 MB file is a few hundred reads, small enough that it is nothing to hold.
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Taken:
    """What the object really is, as opposed to what its upload claimed."""

    sha256: str
    size: int
    stored_at: str


def of(s3: Any, bucket: str, key: str, version_id: str | None) -> Taken:
    """The object's digest, its real size, and when storage took it.

    `version_id` is what the worker was told was created. Naming it means a file replaced between
    the event and this call is not the one fingerprinted — the digest belongs to a version, and
    verifying it later reads that same version (REQ-010, T039).
    """
    at = {"VersionId": version_id} if version_id else {}
    head = s3.head_object(Bucket=bucket, Key=key, **at)

    body = s3.get_object(Bucket=bucket, Key=key, **at)["Body"]
    running = hashlib.sha256()
    size = 0
    while chunk := body.read(CHUNK):
        running.update(chunk)
        size += len(chunk)

    return Taken(
        sha256=running.hexdigest(),
        size=size,
        stored_at=stamp(head["LastModified"]),
    )


def head_size(s3: Any, bucket: str, key: str, version_id: str | None) -> int:
    """How big the object really is, before a byte of it is read — which is what catches a client
    that got around the upload policy (evidence.md §4)."""
    at = {"VersionId": version_id} if version_id else {}
    return int(s3.head_object(Bucket=bucket, Key=key, **at)["ContentLength"])


def stamp(when: Any) -> str:
    """S3's LastModified, in the one format this project writes times in."""
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
