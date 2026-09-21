"""The only code that reads or writes DynamoDB (ADR-0011, docs/design/domain-model.md §6).

Three rules hold everywhere in this file, and nowhere else has to remember them:

1. **Every call names a tenant.** `tenant_id` is the first argument of everything that touches a
   tenant's data, and it becomes the partition key. There is no call that reads across tenants,
   and no `Scan` anywhere, so one tenant's data is not merely filtered out of another's answer —
   it is in a partition the query never reaches (REQ-001).
2. **A write that must happen once carries its condition.** A document is created with
   `attribute_not_exists(pk)` and a digest is written with `attribute_not_exists(sha256)`, so a
   job delivered twice writes nothing the second time and the first digest stands (REQ-008,
   ADR-0007). Those calls answer True when they wrote and False when the write was already there,
   which is a worker's "already done", not an error.
3. **The audit log is only ever appended to.** `append_audit` puts an entry under a key nothing
   else can take; there is no call here that updates or deletes one, and the functions' IAM
   policies don't allow it either (REQ-011).
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from tokelo.core import model
from tokelo.core.model import (
    AuditAction,
    AuditEntry,
    Clause,
    Document,
    DocumentKind,
    DocumentStatus,
    Dossier,
    DossierStatus,
    Lease,
    LeaseStatus,
    Page,
    StoredDocument,
    TimelineEntry,
)

FAILED_CONDITION = "ConditionalCheckFailedException"


class Store:
    """The tenants' table and the audit table, from the function's environment."""

    def __init__(self, endpoint_url: str | None = None) -> None:
        # boto3 ships no types, so this is where a typed codebase meets an untyped SDK. The two
        # tables are the only things that cross the line.
        dynamodb: Any = boto3.resource("dynamodb", endpoint_url=endpoint_url)
        self._table: Any = dynamodb.Table(os.environ["TOKELO_TABLE"])
        self._audit: Any = dynamodb.Table(os.environ["TOKELO_AUDIT_TABLE"])

    # ------------------------------------------------------------- the tenant ---
    def create_tenant(self, tenant_id: str, created_at: str) -> str:
        """Make the tenant's item on their first request, and answer the pseudonym their audit
        entries are filed under. Called again, it answers the pseudonym already there: the
        tenant's identity must not change under their own audit trail."""
        subject = uuid.uuid4().hex
        try:
            self._table.put_item(
                Item={
                    "pk": model.tenant_pk(tenant_id),
                    "sk": model.tenant_sk(),
                    "type": "tenant",
                    "created_at": created_at,
                    "audit_subject": subject,
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
            return subject
        except ClientError as e:
            if e.response["Error"]["Code"] != FAILED_CONDITION:
                raise
        existing = self.get_tenant(tenant_id)
        assert existing is not None  # the condition failed, so it is there
        return existing["audit_subject"]

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        answer = self._table.get_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.tenant_sk()}
        )
        return answer.get("Item")

    # ----------------------------------------------------------- the documents ---
    def create_document(self, tenant_id: str, document: Document) -> bool:
        """True when this call created it, False when it was already there (ADR-0007)."""
        return self._put_once(
            {"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document.id)}
            | document.item()
        )

    def record_stored(
        self, tenant_id: str, document_id: str, s3_version_id: str, sha256: str, stored_at: str
    ) -> bool:
        """The object arrived: its version, its digest, and `stored`. The digest is written once
        and never changes, so this answers False if one is already there (REQ-008)."""
        try:
            self._table.update_item(
                Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
                UpdateExpression=(
                    "SET sha256 = :sha256, s3_version_id = :version, "
                    "stored_at = :at, #status = :status"
                ),
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(sha256)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":sha256": sha256,
                    ":version": s3_version_id,
                    ":at": stored_at,
                    ":status": str(DocumentStatus.STORED),
                },
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == FAILED_CONDITION:
                return False
            raise

    def set_document_status(
        self,
        tenant_id: str,
        document_id: str,
        status: DocumentStatus,
        failure_reason: str | None = None,
    ) -> None:
        expression = "SET #status = :status"
        values: dict[str, Any] = {":status": str(status)}
        if failure_reason is not None:
            expression += ", failure_reason = :reason"
            values[":reason"] = failure_reason
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
        )

    def set_capture(self, tenant_id: str, document_id: str, capture: model.Capture) -> None:
        """What the photo carried, and only that: a field it doesn't have stays absent (REQ-009)."""
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
            UpdateExpression="SET capture = :capture",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":capture": capture.item()},
        )

    def set_lease(
        self,
        tenant_id: str,
        document_id: str,
        page_count: int,
        pages_done: int,
        status: LeaseStatus,
    ) -> None:
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
            UpdateExpression="SET lease = :lease",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={
                ":lease": Lease(page_count=page_count, pages_done=pages_done, status=status).item()
            },
        )

    def set_lease_status(self, tenant_id: str, document_id: str, status: LeaseStatus) -> None:
        """Where the reading got to, without restating the page counts. `reading` → `analysed`
        or `failed` (domain-model.md §5); the counts belong to the reading, not to this."""
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
            UpdateExpression="SET lease.#status = :status",
            ConditionExpression="attribute_exists(lease)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": str(status)},
        )

    def put_page(self, tenant_id: str, document_id: str, page: Page) -> bool:
        """Insert one page, once. True when this call wrote it and False when it was already
        there (ADR-0007).

        The answer is what the fan-out counts on: `pages_done` may only move when a page was
        really inserted, or a job delivered twice would move the lease past its own last page
        (ocr.md §4).
        """
        return self._put_once(
            {
                "pk": model.tenant_pk(tenant_id),
                "sk": model.page_sk(document_id, page.number),
            }
            | page.item()
        )

    def finished_page(self, tenant_id: str, document_id: str) -> int:
        """One more page read, and the new total.

        This is the number two invocations race for: whoever sees it reach `page_count` runs the
        analysis (ocr.md §4). The update is atomic and answers what it wrote, so exactly one
        caller can ever see the count arrive — no lock, and no second analysis.
        """
        answer = self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.document_sk(document_id)},
            UpdateExpression="SET lease.pages_done = lease.pages_done + :one",
            ConditionExpression="attribute_exists(lease)",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return model.whole(answer["Attributes"]["lease"]["pages_done"])

    def put_clause(self, tenant_id: str, document_id: str, clause: Clause) -> None:
        self._table.put_item(
            Item={
                "pk": model.tenant_pk(tenant_id),
                "sk": model.clause_sk(document_id, clause.ordinal),
            }
            | clause.item()
        )

    def get_document(self, tenant_id: str, document_id: str) -> StoredDocument | None:
        """The document, its pages and its clauses, in one query (§6). None when the tenant has
        no such document — including when it is someone else's, which the API answers as 404."""
        items = self._query(model.tenant_pk(tenant_id), model.document_sk(document_id))
        document = next((i for i in items if i.get("type") == "document"), None)
        if document is None:
            return None
        return StoredDocument(
            document=Document.read(document),
            pages=[Page.read(i) for i in items if i.get("type") == "page"],
            clauses=[Clause.read(i) for i in items if i.get("type") == "clause"],
        )

    def list_documents(self, tenant_id: str, kind: DocumentKind | None = None) -> list[Document]:
        items = self._query(model.tenant_pk(tenant_id), "DOC#")
        documents = [Document.read(i) for i in items if i.get("type") == "document"]
        return [d for d in documents if kind is None or d.kind is kind]

    # ------------------------------------------------------------ the timeline ---
    def add_timeline_entry(self, tenant_id: str, entry: TimelineEntry) -> None:
        self._table.put_item(
            Item={
                "pk": model.tenant_pk(tenant_id),
                "sk": model.timeline_sk(entry.occurred_at, entry.id),
            }
            | entry.item()
        )

    def list_timeline(self, tenant_id: str) -> list[TimelineEntry]:
        """In the order things happened: the time is in the sort key (§3)."""
        items = self._query(model.tenant_pk(tenant_id), "TIMELINE#")
        return [TimelineEntry.read(i) for i in items]

    # ------------------------------------------------------------- the dossiers ---
    def create_dossier(self, tenant_id: str, dossier: Dossier) -> bool:
        return self._put_once(
            {"pk": model.tenant_pk(tenant_id), "sk": model.dossier_sk(dossier.id)} | dossier.item()
        )

    def get_dossier(self, tenant_id: str, dossier_id: str) -> Dossier | None:
        answer = self._table.get_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.dossier_sk(dossier_id)}
        )
        item = answer.get("Item")
        return Dossier.read(item) if item else None

    def finish_dossier(
        self, tenant_id: str, dossier_id: str, s3_key: str, sha256: str, ready_at: str
    ) -> None:
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.dossier_sk(dossier_id)},
            UpdateExpression=(
                "SET #status = :status, s3_key = :key, sha256 = :sha256, ready_at = :at"
            ),
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": str(DossierStatus.READY),
                ":key": s3_key,
                ":sha256": sha256,
                ":at": ready_at,
            },
        )

    def set_dossier_status(
        self,
        tenant_id: str,
        dossier_id: str,
        status: DossierStatus,
        failure_reason: str | None = None,
    ) -> None:
        expression = "SET #status = :status"
        values: dict[str, Any] = {":status": str(status)}
        if failure_reason is not None:
            expression += ", failure_reason = :reason"
            values[":reason"] = failure_reason
        self._table.update_item(
            Key={"pk": model.tenant_pk(tenant_id), "sk": model.dossier_sk(dossier_id)},
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
        )

    # ------------------------------------------------------------ the audit log ---
    def append_audit(
        self,
        subject: str,
        action: AuditAction,
        target_id: str,
        detail: dict[str, Any],
        at: str = "",
    ) -> str:
        """Append one entry, under a key nothing else takes. There is no call here that changes
        or removes one, and the functions' roles can't either (REQ-011)."""
        at = at or _now()
        entry_id = uuid.uuid4().hex
        self._audit.put_item(
            Item={
                "pk": model.audit_pk(subject),
                "sk": model.audit_sk(at, entry_id),
                "at": at,
                "action": str(action),
                "target_id": target_id,
                "detail": detail,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return entry_id

    def list_audit(self, subject: str) -> list[AuditEntry]:
        answer = self._audit.query(KeyConditionExpression=Key("pk").eq(model.audit_pk(subject)))
        return [AuditEntry.read(i) for i in answer.get("Items", [])]

    # ---------------------------------------------------------- deleting it all ---
    def delete_tenant(self, tenant_id: str) -> int:
        """Everything in the tenant's partition, in batches, and the count of what went. Their
        audit entries are in the other table and stay: the tenant item held the only mapping to
        them, so what is left names nobody (REQ-016)."""
        gone = 0
        keys = [
            {"pk": item["pk"], "sk": item["sk"]}
            for item in self._query(model.tenant_pk(tenant_id), "")
        ]
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)
                gone += 1
        return gone

    # ---------------------------------------------------------------- the query ---
    def _query(self, pk: str, sk_prefix: str) -> list[dict[str, Any]]:
        """Every item under one partition key, with the pages this table hands back followed.
        The partition key is always given: there is no Scan in this project (§6)."""
        condition = Key("pk").eq(pk)
        if sk_prefix:
            condition = condition & Key("sk").begins_with(sk_prefix)
        items: list[dict[str, Any]] = []
        start: dict[str, Any] | None = None
        while True:
            answer = self._table.query(
                KeyConditionExpression=condition,
                **({"ExclusiveStartKey": start} if start else {}),
            )
            items.extend(answer.get("Items", []))
            start = answer.get("LastEvaluatedKey")
            if not start:
                return items

    def _put_once(self, item: dict[str, Any]) -> bool:
        try:
            self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == FAILED_CONDITION:
                return False
            raise


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
