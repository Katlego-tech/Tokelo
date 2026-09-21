"""The items Tokelo stores, and the keys they live under (docs/design/domain-model.md §3).

Everything a tenant owns is one item in one partition, `pk = TENANT#<tenant id>`, with the item's
path under that tenant as its sort key. That is what makes a tenant's data a query rather than a
filter, and what makes another tenant's data unreachable (REQ-001).

Nothing here talks to DynamoDB: `store.py` does that, and only it. These types are the shape both
sides agree on."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

# ------------------------------------------------------------------ the keys ---
# A number in a sort key is padded, because a sort key sorts as text: PAGE#0002 before PAGE#0010.
WIDTH = 4


def tenant_pk(tenant_id: str) -> str:
    return f"TENANT#{tenant_id}"


def tenant_sk() -> str:
    return "TENANT"


def document_sk(document_id: str) -> str:
    return f"DOC#{document_id}"


def page_sk(document_id: str, number: int) -> str:
    return f"DOC#{document_id}#PAGE#{number:0{WIDTH}d}"


def clause_sk(document_id: str, ordinal: int) -> str:
    return f"DOC#{document_id}#CLAUSE#{ordinal:0{WIDTH}d}"


def timeline_sk(occurred_at: str, entry_id: str) -> str:
    return f"TIMELINE#{occurred_at}#{entry_id}"


def dossier_sk(dossier_id: str) -> str:
    return f"DOSSIER#{dossier_id}"


def audit_pk(subject: str) -> str:
    return f"SUBJECT#{subject}"


def audit_sk(at: str, entry_id: str) -> str:
    return f"{at}#{entry_id}"


# --------------------------------------------------------- the enumerations ---
class DocumentKind(StrEnum):
    LEASE = "lease"
    PHOTO = "photo"
    NOTICE = "notice"
    CHAT = "chat"


class DocumentStatus(StrEnum):
    REQUESTED = "requested"
    STORED = "stored"
    PROCESSED = "processed"
    FAILED = "failed"
    EXPIRED = "expired"


class LeaseStatus(StrEnum):
    READING = "reading"
    ANALYSED = "analysed"
    FAILED = "failed"


class PageSource(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"


class TimelineSource(StrEnum):
    CAPTURE = "capture"
    NOTICE = "notice"
    CHAT_MESSAGE = "chat_message"


class DossierStatus(StrEnum):
    REQUESTED = "requested"
    COMPILING = "compiling"
    READY = "ready"
    FAILED = "failed"


class AuditAction(StrEnum):
    UPLOAD = "upload"
    VERIFY = "verify"
    DOSSIER = "dossier"
    DELETE_ACCOUNT = "delete_account"


# ------------------------------------------------------------------ the items ---
def whole(value: Any) -> int:
    """A number as DynamoDB gives it back (Decimal), as the number it is."""
    return int(value) if isinstance(value, Decimal) else int(value)


@dataclass(frozen=True)
class Capture:
    """A photo's EXIF, where it has any. A field that isn't there is not invented: the API shows
    "not recorded" (REQ-009)."""

    captured_at: str | None = None
    device: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def item(self) -> dict[str, Any]:
        """A field the photo didn't carry is left out, not stored as null.

        The coordinates go in as `Decimal`: DynamoDB has no float, and boto3 refuses one rather
        than rounding it quietly. `Decimal(str(...))` and not `Decimal(float)`, so 28.188 is
        stored as 28.188 and not as the binary expansion nearest to it.
        """
        return {
            k: Decimal(str(v)) if isinstance(v, float) else v
            for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def read(cls, item: dict[str, Any]) -> Capture:
        return cls(
            captured_at=item.get("captured_at"),
            device=item.get("device"),
            latitude=float(item["latitude"]) if item.get("latitude") is not None else None,
            longitude=float(item["longitude"]) if item.get("longitude") is not None else None,
        )


@dataclass(frozen=True)
class Lease:
    """A lease's reading progress, kept on the document it belongs to."""

    page_count: int
    pages_done: int
    status: LeaseStatus

    def item(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "pages_done": self.pages_done,
            "status": str(self.status),
        }

    @classmethod
    def read(cls, item: dict[str, Any]) -> Lease:
        return cls(
            page_count=whole(item["page_count"]),
            pages_done=whole(item["pages_done"]),
            status=LeaseStatus(item["status"]),
        )


@dataclass(frozen=True)
class Document:
    id: str
    kind: DocumentKind
    status: DocumentStatus
    s3_key: str
    content_type: str
    size_bytes: int
    requested_at: str
    s3_version_id: str | None = None
    sha256: str | None = None
    stored_at: str | None = None
    failure_reason: str | None = None
    capture: Capture | None = None
    lease: Lease | None = None

    def item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "document",
            "id": self.id,
            "kind": str(self.kind),
            "status": str(self.status),
            "s3_key": self.s3_key,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "requested_at": self.requested_at,
        }
        for name in ("s3_version_id", "sha256", "stored_at", "failure_reason"):
            if getattr(self, name) is not None:
                item[name] = getattr(self, name)
        if self.capture is not None:
            item["capture"] = self.capture.item()
        if self.lease is not None:
            item["lease"] = self.lease.item()
        return item

    @classmethod
    def read(cls, item: dict[str, Any]) -> Document:
        return cls(
            id=item["id"],
            kind=DocumentKind(item["kind"]),
            status=DocumentStatus(item["status"]),
            s3_key=item["s3_key"],
            content_type=item["content_type"],
            size_bytes=whole(item["size_bytes"]),
            requested_at=item["requested_at"],
            s3_version_id=item.get("s3_version_id"),
            sha256=item.get("sha256"),
            stored_at=item.get("stored_at"),
            failure_reason=item.get("failure_reason"),
            capture=Capture.read(item["capture"]) if item.get("capture") else None,
            lease=Lease.read(item["lease"]) if item.get("lease") else None,
        )


@dataclass(frozen=True)
class Page:
    number: int
    source: PageSource
    text: str
    readable: bool = True

    def item(self) -> dict[str, Any]:
        return {
            "type": "page",
            "number": self.number,
            "source": str(self.source),
            "text": self.text,
            "readable": self.readable,
        }

    @classmethod
    def read(cls, item: dict[str, Any]) -> Page:
        return cls(
            number=whole(item["number"]),
            source=PageSource(item["source"]),
            text=item["text"],
            readable=bool(item["readable"]),
        )


@dataclass(frozen=True)
class Clause:
    ordinal: int
    label: str
    first_page: int
    text: str
    # Each flag keeps the explanation and sections it was shown with, and the catalogue version,
    # so what the tenant saw stays reproducible after the catalogue improves (docs/design/ocr.md).
    flags: list[dict[str, Any]] = field(default_factory=list)

    def item(self) -> dict[str, Any]:
        return {
            "type": "clause",
            "ordinal": self.ordinal,
            "label": self.label,
            "first_page": self.first_page,
            "text": self.text,
            "flags": self.flags,
        }

    @classmethod
    def read(cls, item: dict[str, Any]) -> Clause:
        return cls(
            ordinal=whole(item["ordinal"]),
            label=item["label"],
            first_page=whole(item["first_page"]),
            text=item["text"],
            flags=list(item.get("flags", [])),
        )


@dataclass(frozen=True)
class TimelineEntry:
    id: str
    occurred_at: str
    source: TimelineSource
    summary: str
    document_id: str

    def item(self) -> dict[str, Any]:
        return {
            "type": "timeline",
            "id": self.id,
            "occurred_at": self.occurred_at,
            "source": str(self.source),
            "summary": self.summary,
            "document_id": self.document_id,
        }

    @classmethod
    def read(cls, item: dict[str, Any]) -> TimelineEntry:
        return cls(
            id=item["id"],
            occurred_at=item["occurred_at"],
            source=TimelineSource(item["source"]),
            summary=item["summary"],
            document_id=item["document_id"],
        )


@dataclass(frozen=True)
class Dossier:
    id: str
    status: DossierStatus
    document_ids: list[str]
    requested_at: str
    s3_key: str | None = None
    sha256: str | None = None
    ready_at: str | None = None
    failure_reason: str | None = None

    def item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "dossier",
            "id": self.id,
            "status": str(self.status),
            "document_ids": list(self.document_ids),
            "requested_at": self.requested_at,
        }
        for name in ("s3_key", "sha256", "ready_at", "failure_reason"):
            if getattr(self, name) is not None:
                item[name] = getattr(self, name)
        return item

    @classmethod
    def read(cls, item: dict[str, Any]) -> Dossier:
        return cls(
            id=item["id"],
            status=DossierStatus(item["status"]),
            document_ids=list(item.get("document_ids", [])),
            requested_at=item["requested_at"],
            s3_key=item.get("s3_key"),
            sha256=item.get("sha256"),
            ready_at=item.get("ready_at"),
            failure_reason=item.get("failure_reason"),
        )


@dataclass(frozen=True)
class AuditEntry:
    """In its own table, under a pseudonym: deleting the account deletes the mapping, which leaves
    these entries without anyone to resolve them (REQ-011, REQ-016)."""

    at: str
    action: AuditAction
    target_id: str
    detail: dict[str, Any]

    @classmethod
    def read(cls, item: dict[str, Any]) -> AuditEntry:
        return cls(
            at=item["at"],
            action=AuditAction(item["action"]),
            target_id=item["target_id"],
            detail=dict(item.get("detail", {})),
        )


@dataclass(frozen=True)
class StoredDocument:
    """A document with everything under it, as one query returns them (§6)."""

    document: Document
    pages: list[Page] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
