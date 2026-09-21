"""Running the rules over a lease, and storing what they found (REQ-005, REQ-007; ocr.md §4).

This module is the join. The reader gives back pages ([pages.py](pages.py)), the splitter turns
them into clauses ([clauses.py](clauses.py)), the catalogue holds the rules ([rules](rules)) — and
here every rule is run against every clause, and what matches becomes a flag stored against the
lease, with the sentence the tenant reads, the sections it rests on, and the catalogue's version.

Two things it deliberately does not do.

**It does not decide.** A rule says which law is relevant to a clause. Whether that clause is
enforceable against this tenant in these circumstances is for the tenant, and if it comes to it
the Tribunal or the court. So a clause no rule matched says `NO_ISSUE` — a statement about
Tokelo's checks, not about the clause (REQ-007). Tokelo has ten rules; the law has rather more.

**It does not skip the quiet clauses.** A tenant reads their own lease here, not a list of its
worst lines, so every clause the splitter found comes back — most of them with nothing against
them, and that is worth seeing.
"""

from tokelo.core.model import Clause, DocumentStatus, LeaseStatus
from tokelo.core.store import Store
from tokelo.ocr import clauses as splitter
from tokelo.ocr import rules

# What a clause with no flag says, and the only thing it may say (REQ-007; api.md §6). It is
# about the checks that ran, not about the clause: "lawful" is a word this project never uses.
NO_ISSUE = "no issue found by these checks"


def analyse(pages: list[str], catalogue: rules.Catalogue | None = None) -> list[Clause]:
    """A lease's readable pages, in page order, as clauses carrying their flags.

    An unreadable page is passed in as an empty string rather than left out: its number still
    belongs to it, and the clauses after it must keep the page they really start on (REQ-004).
    """
    book = catalogue or rules.catalogue()
    return [
        Clause(
            ordinal=clause.ordinal,
            label=clause.label,
            first_page=clause.first_page,
            text=clause.text,
            flags=[flag(rule, book.version) for rule in book.rules if rule.matches(clause.text)],
        )
        for clause in splitter.split(pages)
    ]


def flag(rule: rules.Rule, catalogue_version: str) -> dict[str, object]:
    """One match, as a tenant is shown it and as it is kept.

    The explanation and the sections are copied rather than referred to, because the catalogue
    will improve: what a tenant read, and took to the Tribunal, has to still read the same way
    afterwards. The version says which catalogue said it.
    """
    return {
        "rule_id": rule.id,
        "explanation": rule.explanation,
        "sections": rule.sections(),
        "catalogue_version": catalogue_version,
    }


def finding(clause: Clause) -> str | None:
    """What to show for a clause with no flags, or None when it has some (REQ-007)."""
    return None if clause.flags else NO_ISSUE


def record(store: Store, tenant_id: str, document_id: str, analysed: list[Clause]) -> None:
    """Store the clauses, and finish the lease.

    Every write here is one a redelivered job may repeat (ADR-0007): a clause is keyed by its
    ordinal, so the second run rewrites the same item rather than adding one, and the statuses
    are set to the value they already hold. The lease's page counts aren't touched — they are
    the reading's, not the analysis's.
    """
    for clause in analysed:
        store.put_clause(tenant_id, document_id, clause)
    store.set_lease_status(tenant_id, document_id, LeaseStatus.ANALYSED)
    store.set_document_status(tenant_id, document_id, DocumentStatus.PROCESSED)
