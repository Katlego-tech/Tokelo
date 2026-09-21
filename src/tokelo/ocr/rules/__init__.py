"""The rule catalogue: what turns a clause in a lease into a flag on a tenant's screen
(docs/design/ocr.md §3, §6; REQ-005, REQ-006, REQ-007).

A rule is deliberately small. It matches a clause with plain regular expressions, cites the
sections it rests on, and carries the sentence a tenant reads. It does not decide anything: it
says which law is relevant and leaves the conclusion where it belongs — with the tenant, and if
it comes to it, with the Tribunal.

Three things are refused when the catalogue loads, rather than found out later in front of a
tenant:

* a rule citing a section nobody curated (REQ-006) — the ceiling is `docs/legal/`;
* a rule whose own example it cannot match, or whose counter-example it does;
* files that disagree about the catalogue's version, since the version is stored on every flag
  and has to mean one thing.
"""

import re
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from tokelo.core import sources


class BadCatalogue(Exception):
    """The catalogue can't be trusted, so it doesn't load."""


@dataclass(frozen=True)
class Rule:
    id: str
    section_ids: list[str]
    explanation: str
    example: str
    counter_example: str
    any_of: list[re.Pattern[str]] = field(default_factory=list)
    all_of: list[re.Pattern[str]] = field(default_factory=list)
    none_of: list[re.Pattern[str]] = field(default_factory=list)

    def matches(self, clause: str) -> bool:
        """At least one of any_of, all of all_of, and none of none_of (ocr.md §3)."""
        if self.any_of and not any(p.search(clause) for p in self.any_of):
            return False
        if not all(p.search(clause) for p in self.all_of):
            return False
        return not any(p.search(clause) for p in self.none_of)

    def sections(self) -> list[dict[str, str]]:
        """The sections this rule cites, as api.md §6's SectionRef."""
        return [sources.section(i).reference() for i in self.section_ids]


@dataclass(frozen=True)
class Catalogue:
    version: str
    rules: list[Rule]


def compile_patterns(patterns: list[str], where: str) -> list[re.Pattern[str]]:
    try:
        return [re.compile(p, re.I) for p in patterns]
    except re.error as bad:
        raise BadCatalogue(f"{where}: {bad}") from bad


def load(data: dict[str, Any], where: str) -> Catalogue:
    """One file's worth of rules, checked. `where` names the file in any complaint."""
    version = str(data.get("catalogue_version", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", version):
        raise BadCatalogue(f"{where}: catalogue_version must read like 2026-09-21.1")

    curated = sources.ids()
    rules: list[Rule] = []
    for raw in data.get("rule", []):
        rule_id = str(raw.get("id", "")) or "a rule with no id"
        for cited in raw.get("section_ids", []):
            if cited not in curated:
                raise BadCatalogue(
                    f"{where}: {rule_id} cites {cited}, which is not a curated section "
                    f"(docs/legal/). A flag must rest on law this project holds."
                )
        if not raw.get("section_ids"):
            raise BadCatalogue(f"{where}: {rule_id} cites no section (REQ-006)")

        rule = Rule(
            id=rule_id,
            section_ids=list(raw["section_ids"]),
            explanation=str(raw["explanation"]).strip(),
            example=str(raw["example"]),
            counter_example=str(raw["counter_example"]),
            any_of=compile_patterns(raw.get("any_of", []), f"{where}: {rule_id}"),
            all_of=compile_patterns(raw.get("all_of", []), f"{where}: {rule_id}"),
            none_of=compile_patterns(raw.get("none_of", []), f"{where}: {rule_id}"),
        )
        if not rule.matches(rule.example):
            raise BadCatalogue(f"{where}: {rule_id} does not match its own example")
        if rule.matches(rule.counter_example):
            raise BadCatalogue(f"{where}: {rule_id} matches its counter-example")
        rules.append(rule)

    return Catalogue(version=version, rules=rules)


@cache
def catalogue() -> Catalogue:
    """Every rule file in this directory, as one catalogue. They must agree on the version."""
    version = ""
    rules: list[Rule] = []
    for path in sorted(Path(__file__).parent.glob("*.toml")):
        loaded = load(tomllib.loads(path.read_text(encoding="utf-8")), path.name)
        if version and loaded.version != version:
            raise BadCatalogue(
                f"{path.name} is catalogue {loaded.version}, but another file is {version}: "
                "every flag records one version, so the files must agree"
            )
        version = loaded.version
        rules.extend(loaded.rules)

    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise BadCatalogue("two rules share an ID")
    return Catalogue(version=version, rules=rules)
