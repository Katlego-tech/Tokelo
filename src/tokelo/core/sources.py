"""The curated legal sources (REQ-006; docs/legal/).

Tokelo may cite a section of the law only if that section is in `docs/legal/sections/`. The rule
catalogue is held to it when it loads (T032), and so is every navigator topic (T045): a rule that
names an ID which isn't here is refused, rather than shown to a tenant as an explanation with no
law behind it.

That makes this directory the ceiling on everything the product says about the law, which is why
each file carries not only the text but where it was taken from, on what day, and which
amendments it includes. A tenant standing in front of a Tribunal must be able to check the line
they were shown against the gazette it came from.
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

FRONT_MATTER = "+++"


class NotCurated(Exception):
    """A section was asked for that nobody curated. It must not be cited."""


@dataclass(frozen=True)
class Source:
    """Where a section's text was taken from, and when."""

    publisher: str
    url: str
    pages: str
    retrieved: str
    as_at: str
    amendments: str


@dataclass(frozen=True)
class Section:
    id: str
    act: str
    number: str
    title: str
    text: str
    source: Source

    def reference(self) -> dict[str, str]:
        """api.md §6's SectionRef: what a tenant is shown beside an explanation."""
        return {"id": self.id, "act": self.act, "section": self.number, "title": self.title}


def root() -> Path:
    """Where the curated sections live: beside the code in an image, in the repository here."""
    import os

    if named := os.environ.get("TOKELO_LEGAL_ROOT"):
        return Path(named)
    packaged = Path(__file__).resolve().parents[2] / "legal" / "sections"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "docs" / "legal" / "sections"


def parse(text: str, where: str) -> Section:
    """One curated file: TOML front matter between +++ lines, then the section's own words."""
    if not text.startswith(FRONT_MATTER):
        raise ValueError(f"{where}: a curated section starts with {FRONT_MATTER}")
    _, front, body = text.split(FRONT_MATTER, 2)
    fields: dict[str, Any] = tomllib.loads(front)
    source = fields.get("source", {})
    try:
        return Section(
            id=fields["id"],
            act=fields["act"],
            number=str(fields["section"]),
            title=fields["title"],
            text=body.strip(),
            source=Source(
                publisher=source["publisher"],
                url=source["url"],
                pages=str(source.get("pages", "")),
                retrieved=str(source["retrieved"]),
                as_at=str(source["as_at"]),
                amendments=source["amendments"],
            ),
        )
    except KeyError as missing:
        raise ValueError(f"{where}: a curated section needs {missing}") from missing


@cache
def _sections() -> dict[str, Section]:
    found: dict[str, Section] = {}
    for path in sorted(root().glob("*.md")):
        section = parse(path.read_text(encoding="utf-8"), path.name)
        if section.id in found:
            raise ValueError(f"{path.name}: {section.id} is already curated")
        found[section.id] = section
    return found


def all_sections() -> list[Section]:
    return list(_sections().values())


def ids() -> frozenset[str]:
    """Every ID a rule or a topic may cite (REQ-006)."""
    return frozenset(_sections())


def section(wanted: str) -> Section:
    try:
        return _sections()[wanted]
    except KeyError:
        raise NotCurated(
            f"{wanted} is not a curated section: only {', '.join(sorted(ids()))} may be cited"
        ) from None
