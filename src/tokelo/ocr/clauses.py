"""Splitting a lease into clauses (docs/design/ocr.md §6; REQ-005).

A flag is shown against a clause, so this decides what a tenant is shown. The rule is the
design's: a clause starts at a line that begins with a clause number — `12.`, `12.3`, `(a)`,
`Clause 12` — a heading in capitals belongs to the clause beneath it, and whatever comes before
the first number is clause 0, the preamble.

The hard part is not finding numbers, it is not finding them where they aren't. A lease is full
of lines that open with a figure and mean nothing by it: an amount, a date, a street number. A
clause number is followed by a full stop or a bracket and then a space, and that is what is
required here — so `1.1 The rental is…` starts a clause and `R500 is payable…`, `28 February
2027 is…` and `14B Marabastad Road…` do not.
"""

import re
from dataclasses import dataclass

# 12.3  |  12.3.1 — a dotted number; the trailing full stop is optional because leases use both.
NUMBERED = re.compile(r"^(?P<label>\d+(?:\.\d+)+)\.?\s+(?=\S)")
# 12. — a bare number *must* carry its full stop, or "28 February 2027 is the last day…" becomes
# clause 28 and the sentence it opens is cut in half.
SECTION = re.compile(r"^(?P<label>\d+)\.\s+(?=\S)")
# (a)  |  (iv)  — a letter or roman numeral in brackets.
LETTERED = re.compile(r"^(?P<label>\((?:[a-z]{1,2}|[ivxlc]{1,5})\))\s+(?=\S)")
# Clause 12  |  CLAUSE 12.3
SPELT_OUT = re.compile(r"^(?P<label>[Cc]lause\s+\d+(?:\.\d+)*)\s+(?=\S)")

# A heading: a line with no lowercase letters and no sentence in it — "7. BREACH", "RENTAL".
HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?[^a-z]{2,}$")

PREAMBLE = "Preamble"


@dataclass(frozen=True)
class Clause:
    """One clause of a lease, as the rules see it and as a tenant is shown it."""

    ordinal: int
    label: str
    first_page: int
    text: str


def label_of(line: str) -> str | None:
    """The clause number a line opens with, or None if it doesn't open with one."""
    stripped = line.strip()
    for pattern in (SPELT_OUT, LETTERED, NUMBERED, SECTION):
        found = pattern.match(stripped)
        if found:
            return found.group("label")
    return None


def is_heading(line: str) -> bool:
    """A heading carries no clause of its own: it belongs to what comes under it."""
    stripped = line.strip()
    return bool(stripped) and bool(HEADING.match(stripped))


def split(pages: list[str]) -> list[Clause]:
    """Every clause in a lease, in order, each knowing the page it starts on.

    `pages` is the text of each page, in order — a page that could not be read is an empty
    string, and contributes nothing while still counting towards the page numbers (REQ-004).
    """
    clauses: list[Clause] = []
    lines: list[str] = []
    label = PREAMBLE
    started_on = 1
    held: list[str] = []  # headings waiting for the clause they belong to

    def close() -> None:
        text = "\n".join(lines).strip()
        if text:
            clauses.append(
                Clause(ordinal=len(clauses), label=label, first_page=started_on, text=text)
            )

    for number, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            line = raw.rstrip()
            if is_heading(line):
                held.append(line)
                continue
            found = label_of(line)
            if found is None:
                (lines if lines or clauses or label == PREAMBLE else held).append(line)
                continue
            close()
            lines = [*held, line]
            held = []
            label = found
            started_on = number
    close()
    return clauses
