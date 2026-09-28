"""What a dossier may hold (docs/design/api.md §6, "What a dossier may hold"; REQ-013, REQ-001).

It is checked twice, in the same words. The `api` checks it when the tenant asks (T042). The
`dossier` worker checks it again when it builds (T043), against the documents in the tenant's
partition, whatever the job object says (dossier.md §4). Only then can a job object that names
someone else's file, or a file deleted in between, never reach a PDF.

Three things are refused, each with the reason a tenant reads:
- **nothing, or too much:** an empty selection says so (SPEC.md US3), and more than 150 documents
  is refused before anything is looked up
- **a document that isn't the tenant's:** the same words as one that doesn't exist. Telling them
  apart would confirm that the other tenant's document exists (api.md §8)
- **a document that isn't finished:** one still being read would put half a lease's flags, or
  half an export's messages, into a PDF that looks complete
"""

import re
from collections.abc import Mapping

from tokelo.core.keys import UUID
from tokelo.core.model import Document, DocumentStatus

LIMIT = 150  # api.md §6; the worker's own ceiling on the PDF is dossier.md §4's 100 MB

NOTHING = "Nothing is selected: choose at least one document to put in the dossier."
NOT_YOURS = "A selected document isn't one of yours, or is no longer there."
NOT_A_LIST = "A dossier needs the documents to put in it: document_ids, a list of their IDs."

_ID = re.compile(rf"^{UUID}$")


class Refused(ValueError):
    """The selection can't become a dossier. The message is the reason, for the tenant."""


def chosen(document_ids: object) -> list[str]:
    """The IDs asked for, checked for shape only: a list of strings, each document once in the
    order first chosen, from 1 to LIMIT of them, each a UUID. Raises Refused.

    A string that isn't a UUID is no document of anyone's. It's refused here rather than looked
    up, because the store reads a document by the start of its sort key, where a prefix of a real
    ID would find it (domain-model.md §6).
    """
    if not isinstance(document_ids, list) or not all(isinstance(i, str) for i in document_ids):
        raise Refused(NOT_A_LIST)
    unique = list(dict.fromkeys(document_ids))
    if not unique:
        raise Refused(NOTHING)
    if len(unique) > LIMIT:
        raise Refused(
            f"A dossier can hold at most {LIMIT} documents, and {len(unique)} are selected."
        )
    if not all(_ID.match(i) for i in unique):
        raise Refused(NOT_YOURS)
    return unique


def check(document_ids: list[str], documents: Mapping[str, Document]) -> list[Document]:
    """The documents asked for, in that order, when every one is among the tenant's `documents`
    and finished. Raises Refused with the first reason one isn't."""
    found: list[Document] = []
    for document_id in document_ids:
        document = documents.get(document_id)
        if document is None:
            raise Refused(NOT_YOURS)
        if (reason := unfinished(document)) is not None:
            raise Refused(reason)
        found.append(document)
    return found


def unfinished(document: Document) -> str | None:
    """Why this document can't go into a dossier yet, or None when it can.

    Finished is `processed` with a digest. Its worker marks it so when it's done: a lease together
    with its reading becoming `analysed` (ocr/flags.py), and a photo, notice or export once its
    capture details and timeline entries are written (evidence/handler.py).
    """
    if document.status is DocumentStatus.PROCESSED and document.sha256:
        return None
    kind = document.kind
    match document.status:
        case DocumentStatus.REQUESTED | DocumentStatus.EXPIRED:
            return f"A {kind} in the selection was never uploaded, so there is nothing to include."
        case DocumentStatus.FAILED:
            return (
                f"A {kind} in the selection couldn't be processed, so it can't go into a "
                "dossier. Upload it again, then choose the new one."
            )
        case _:
            return f"A {kind} in the selection is still being read. Try again once it's finished."
