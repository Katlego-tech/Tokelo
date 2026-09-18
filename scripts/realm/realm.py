#!/usr/bin/env python3
"""realm: Secret Realm's checks. scripts/realm/checks.sh runs them from the gate.

    realm req-lint           REQUIREMENTS.md: IDs, levels, states, verification, NFR targets
    realm trace [--write]    every requirement's tasks, commits, tests and releases; fails on a
                             broken link. --write also writes the matrix to docs/rtm.md.
    realm adr-check          docs/adr/: numbering, statuses, sections; a decided ADR's text is
                             frozen (only its Status line may change) and it's never deleted
    realm design-check       C4 levels 1 and 2 in docs/architecture/, and a STRIDE threats
                             section in every design doc in docs/design/
    realm gates              GATES.md: each stage's gate passes with a dated, evidenced entry,
                             in order (signed in the assured tier)
    realm gate-passed <stage>  exit 0 if that gate has passed (the release asks for Development)
    realm checkov-skips      infra/: every inline checkov skip says why, as ZAP's decisions do
    realm incidents          docs/ops/incidents/: a closed incident has its postmortem and names
                             the change (a commit this repo has, or a PR) that stops a repeat
    realm eol | dora | upstream   the scheduled checks (ops.py): runtime end of life, the monthly
                             delivery metrics, and how far the kit is behind Cultivation
    realm release ...        the release pipeline's helpers (release.py; release.sh calls them)
    realm railway ...        the Railway deploy adapter (railway.py; deploy/railway.sh calls it)
    realm aws ...            the AWS deploy adapter, ECS or Lambda (aws.py; deploy/aws.sh calls it)

It reads realm.toml (the tier, and where tracing starts), REQUIREMENTS.md, TASKS.md, the tests,
the git history, docs/adr/, docs/architecture/, docs/design/ and docs/releases/. DESIGN.md §4 to
§7 are the contracts. Standard library
only; Python 3.11+ (the scripts/realm/realm wrapper fetches one with uv when needed).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

LEVELS = {"BR": "business", "SR": "stakeholder", "REQ": "software", "NFR": "quality"}
ORDER = list(LEVELS)
STATES = (
    "proposed",
    "approved",
    "implemented",
    "verified",
    "released",
    "deprecated",
    "retired",
    "withdrawn",
)
ACTIVE = ("approved", "implemented", "verified", "released")  # need a task and a test
BUILT = ("implemented", "verified", "released")  # need a finished task
METHODS = ("test", "analysis", "inspection", "demonstration")
# ISO/IEC/IEEE 29148, as the SDLC document lists them.
QUALITIES = (
    "unambiguous",
    "necessary",
    "feasible",
    "verifiable",
    "singular",
    "implementation-free",
    "correct",
    "complete",
    "consistent",
)
# ISO/IEC 25010:2023, plus the 2011 names still in common use.
CHARACTERISTICS = (
    "functional suitability",
    "performance efficiency",
    "compatibility",
    "interaction capability",
    "usability",
    "reliability",
    "security",
    "maintainability",
    "flexibility",
    "portability",
    "safety",
)
PARENTS = {"SR": ("BR",), "REQ": ("SR", "BR"), "NFR": ("BR", "SR", "REQ")}

ID = r"(?:BR|SR|REQ|NFR)-\d{3,}"
TASK_ID = r"T\d{3,}"
BOUND = re.compile(
    r"<=|>=|<|>|≤|≥|=|\b(?:at most|at least|under|over|below|above|within|"
    r"no more than|no less than|less than|more than|fewer than)\b",
    re.I,
)
AMOUNT = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:%|[A-Za-zµ][A-Za-z/]*)")
TICK = "✓✔"

TEST_DIRS = {
    "tests",
    "test",
    "__tests__",
    "spec",
    "specs",
    "e2e",
    "perf",
    "performance",
    "contract",
    "contracts",
    "acceptance",
    "integration",
}
TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$)")
PY_MARK = re.compile(r"pytest\.mark\.req\(([^)]*)\)")
PY_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.M)
JS_TITLE = re.compile(
    r"\b(?:it|test|describe)(?:\.\w+)*\(\s*(['\"`])\s*((?:\[" + ID + r"\]\s*)+)([^'\"`]*)"
)
COMMENT_REQ = re.compile(
    r"^\s*(?:#|//|--|;|/\*|\*)\s*req:\s*(" + ID + r"(?:\s*,\s*" + ID + r")*)", re.I | re.M
)


class RealmError(Exception):
    """A problem the user has to fix before the checks can run at all."""


@dataclass
class Problem:
    where: str
    text: str

    def __str__(self) -> str:
        return f"{self.where}: {self.text}"


@dataclass
class Requirement:
    id: str
    title: str
    line: int
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        return self.id.split("-")[0]

    @property
    def state(self) -> str:
        return self.fields.get("state", "").lower()

    @property
    def parent(self) -> str:
        return self.fields.get("parent", "").strip()

    @property
    def verify(self) -> str:
        return self.fields.get("verify by", "").strip()


@dataclass
class Task:
    id: str
    done: bool
    line: int
    reqs: list[str] = field(default_factory=list)
    req_field: str | None = None


@dataclass
class TestRef:
    where: str
    reqs: list[str]


# ------------------------------------------------------------------ reading ---
def repo_root() -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if r.returncode != 0:
        raise RealmError("not inside a git repository")
    return Path(r.stdout.strip())


def load_config(root: Path) -> dict:
    path = root / "realm.toml"
    if not path.exists():
        raise RealmError("no realm.toml here: this isn't a Secret Realm project")
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise RealmError(f"realm.toml is not valid TOML: {e}") from e
    tier = config.get("realm", {}).get("tier", "")
    if tier not in ("standard", "assured"):
        raise RealmError(f"realm.toml [realm] tier must be standard or assured, not {tier!r}")
    return config


def blank_out(text: str) -> str:
    """Hide HTML comments and fenced code blocks (the examples), keeping line numbers."""

    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
    return re.sub(r"^(```|~~~).*?^\1[^\n]*$", blank, text, flags=re.S | re.M)


def field_key(raw: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", raw).strip().lower()


def parse_requirements(text: str) -> tuple[list[Requirement], list[Problem]]:
    reqs: list[Requirement] = []
    problems: list[Problem] = []
    current: Requirement | None = None
    last_key = ""
    for n, line in enumerate(blank_out(text).splitlines(), 1):
        if re.match(r"^#{1,6}\s", line):
            current = None
            m = re.match(r"^###\s+([A-Z]+-\d+)\s*[—–-]\s*(.*?)\s*$", line)
            if m and re.fullmatch(ID, m.group(1)):
                current = Requirement(m.group(1), m.group(2), n)
                reqs.append(current)
            elif m:
                problems.append(
                    Problem(
                        f"REQUIREMENTS.md:{n}",
                        f"{m.group(1)} isn't a requirement ID: use BR-, SR-, "
                        "REQ- or NFR- and at least three digits",
                    )
                )
            continue
        if current is None:
            continue
        if line.startswith("- "):
            for part in re.split(r"\s+·\s+", line[2:]):
                key, sep, value = part.partition(":")
                if sep:
                    last_key = field_key(key)
                    current.fields[last_key] = value.strip()
        elif line.startswith((" ", "\t")) and line.strip() and last_key:
            current.fields[last_key] += " " + line.strip()
    return reqs, problems


def section(text: str, heading: str) -> str | None:
    """The text under a ## heading that starts with `heading`, up to the next ## heading or
    requirement entry (its own ### subsections stay in). None if there's no such heading."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}[^\n]*\n(.*?)(?=^##\s|^###\s+{ID}|\Z)",
        text,
        flags=re.S | re.M | re.I,
    )
    return None if m is None else m.group(1)


def parse_tasks(text: str) -> list[Task]:
    tasks: list[Task] = []
    current: Task | None = None
    for n, line in enumerate(blank_out(text).splitlines(), 1):
        m = re.match(rf"^\s*- \[([ xX])\]\s+({TASK_ID})\b", line)
        if m:
            current = Task(m.group(2), m.group(1).lower() == "x", n)
            tasks.append(current)
            continue
        if current is None:
            continue
        if re.match(r"^\S", line):
            current = None
            continue
        f = re.match(r"^\s+Req:\s*(.*)$", line)
        if f:
            value = f.group(1).strip()
            current.req_field = value
            current.reqs = re.findall(ID, value)
    return tasks


def tracked_files(root: Path) -> list[str]:
    r = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return [f for f in r.stdout.splitlines() if (root / f).is_file()]


def is_test_file(path: str) -> bool:
    p = Path(path)
    return bool(TEST_DIRS & set(p.parts[:-1])) or bool(TEST_NAME.search(p.name))


def find_tests(root: Path) -> list[TestRef]:
    refs: list[TestRef] = []
    for path in tracked_files(root):
        suffix = Path(path).suffix
        if suffix == ".py" or is_test_file(path):
            try:
                text = (root / path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
        else:
            continue
        if suffix == ".py":
            for m in PY_MARK.finditer(text):
                name = PY_DEF.search(text, m.end())
                where = f"{path}::{name.group(1)}" if name else path
                refs.append(TestRef(where, re.findall(ID, m.group(1))))
        if is_test_file(path):
            for m in JS_TITLE.finditer(text):
                refs.append(
                    TestRef(
                        f'{path} "{m.group(2).strip()} {m.group(3).strip()}"',
                        re.findall(ID, m.group(2)),
                    )
                )
            for m in COMMENT_REQ.finditer(text):
                refs.append(TestRef(path, re.findall(ID, m.group(1))))
    return refs


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def commits(root: Path, since: str) -> list[tuple[str, bool, str]]:
    """(sha, is_merge, subject) for every commit after `since` on the current branch."""
    if since and git(root, "merge-base", "--is-ancestor", since, "HEAD").returncode != 0:
        raise RealmError(
            f"realm.toml [trace] since = {since!r} is not a commit this branch "
            "contains: set it to the project's scaffold commit"
        )
    if git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return []
    rng = f"{since}..HEAD" if since else "HEAD"
    out = git(root, "log", "--format=%H%x09%P%x09%s", rng).stdout
    rows = []
    for line in out.splitlines():
        sha, parents, subject = line.split("\t", 2)
        rows.append((sha, len(parents.split()) > 1, subject))
    return rows


def releases(root: Path) -> dict[str, list[str]]:
    """Requirement ID -> the release versions whose record lists it (docs/releases/v*.md)."""
    shipped: dict[str, list[str]] = defaultdict(list)
    for record in sorted((root / "docs" / "releases").glob("v*.md")):
        m = re.search(
            r"^[-*]\s*Requirements:\s*(.*)$", record.read_text(encoding="utf-8"), flags=re.M
        )
        for rid in re.findall(ID, m.group(1)) if m else []:
            shipped[rid].append(record.stem)
    return shipped


# ----------------------------------------------------------------- req-lint ---
def lint(reqs: list[Requirement], text: str, tier: str) -> list[Problem]:
    problems: list[Problem] = []
    by_id: dict[str, Requirement] = {}
    for r in reqs:
        if r.id in by_id:
            problems.append(
                Problem(
                    f"REQUIREMENTS.md:{r.line}",
                    f"{r.id} is used twice (first on line {by_id[r.id].line})",
                )
            )
        by_id.setdefault(r.id, r)
    assured = tier == "assured"
    for r in reqs:
        problems += [
            Problem(f"REQUIREMENTS.md:{r.line}", f"{r.id}: {text}")
            for text in check(r, by_id, assured)
        ]
    if any(r.state in ACTIVE for r in reqs):
        opscon = section(text, "Operational concept")
        if opscon is None or not blank_out(opscon).strip():
            problems.append(
                Problem(
                    "REQUIREMENTS.md",
                    "requirements are approved, but the "
                    "Operational concept (OpsCon) section is empty",
                )
            )
    return problems


def check(r: Requirement, by_id: dict[str, Requirement], assured: bool) -> list[str]:
    """What's wrong with one entry, as sentences about it."""
    found: list[str] = []
    add = found.append
    if r.state not in STATES:
        add(f"State is {r.state or 'missing'}; use one of: {', '.join(STATES)}")
    level = r.fields.get("level", "").lower()
    if level and level != LEVELS[r.prefix]:
        add(f"Level says {level}, but {r.prefix}- is the {LEVELS[r.prefix]} level")
    if r.prefix != "NFR":
        statement = r.fields.get("statement", "")
        if not statement:
            add("no Statement")
        elif re.search(r"<[^>]+>", statement):
            add("the Statement is still a placeholder")

    needs_parent = r.prefix == "REQ" or (assured and r.prefix in ("SR", "NFR"))
    if r.parent:
        target = by_id.get(r.parent)
        if target is None:
            add(f"its Parent {r.parent} doesn't exist")
        elif target.prefix not in PARENTS.get(r.prefix, ()):
            add(
                f"a {r.prefix}- can't have a {target.prefix}- parent "
                f"(allowed: {', '.join(PARENTS.get(r.prefix, ())) or 'none'})"
            )
    elif needs_parent:
        add(
            f"no Parent: a {LEVELS[r.prefix]} requirement traces to "
            f"{' or '.join(p + '-' for p in PARENTS[r.prefix])}"
            + (" (assured tier)" if r.prefix != "REQ" else "")
        )

    needs_method = r.prefix in ("REQ", "NFR") or assured
    method = r.verify.split()[0].lower() if r.verify else ""
    if method and method not in METHODS:
        add(f"Verify by {r.verify!r}: use test, analysis, inspection or demonstration")
    elif needs_method and not method:
        add(
            "no Verify by (test, analysis, inspection or demonstration)"
            + (
                ": in the assured tier every level fixes it before it's built"
                if assured and r.prefix in ("BR", "SR")
                else ""
            )
        )

    if r.prefix == "NFR":
        characteristic = r.fields.get("characteristic", "").lower()
        if characteristic not in CHARACTERISTICS:
            add(
                f"Characteristic {characteristic or 'missing'}: use an ISO/IEC 25010 one "
                f"({', '.join(CHARACTERISTICS[:3])}…)"
            )
        target = r.fields.get("target", "")
        if not (BOUND.search(target) and AMOUNT.search(target)):
            add(
                "the Target needs a bound on a number with a unit, e.g. "
                "'p95 < 200 ms at 50 requests/second'"
            )
        if not r.fields.get("measured by"):
            add("no Measured by: name the test or tool that measures the target")

    if r.state in ACTIVE:
        quality = r.fields.get("quality", "").lower()
        missing = [q for q in QUALITIES if not re.search(rf"{re.escape(q)}\s*[{TICK}]", quality)]
        if missing:
            add(f"is {r.state} but its quality checklist lacks: {', '.join(missing)}")
    return found


def cmd_req_lint(root: Path, config: dict) -> int:
    path = root / "REQUIREMENTS.md"
    if not path.exists():
        print("!! REQUIREMENTS.md is missing: a realm project keeps its requirements there")
        return 1
    text = path.read_text(encoding="utf-8")
    reqs, problems = parse_requirements(text)
    problems += lint(reqs, text, config["realm"]["tier"])
    for p in problems:
        print(f"!! {p}")
    active = sum(r.state in ACTIVE for r in reqs)
    print(
        f"   req-lint: {len(reqs)} requirement(s), {active} approved or later, "
        f"{len(problems)} problem(s)"
    )
    return 1 if problems else 0


# -------------------------------------------------------------------- trace ---
@dataclass
class Trace:
    reqs: list[Requirement]
    tasks: list[Task]
    tests: list[TestRef]
    history: list[tuple[str, bool, str]]
    shipped: dict[str, list[str]]
    problems: list[Problem] = field(default_factory=list)

    def tasks_for(self, rid: str) -> list[Task]:
        return [t for t in self.tasks if rid in t.reqs]

    def tests_for(self, rid: str) -> list[str]:
        return [t.where for t in self.tests if rid in t.reqs]

    def commits_for(self, task: str) -> list[str]:
        return [
            sha[:7]
            for sha, merge, subject in self.history
            if not merge and re.search(rf"\b{task}\b", subject)
        ]


def trace(root: Path, config: dict) -> Trace:
    text = (
        (root / "REQUIREMENTS.md").read_text(encoding="utf-8")
        if (root / "REQUIREMENTS.md").exists()
        else ""
    )
    reqs, _ = parse_requirements(text)
    tasks_file = root / "TASKS.md"
    tasks = parse_tasks(tasks_file.read_text(encoding="utf-8")) if tasks_file.exists() else []
    since = str(config.get("trace", {}).get("since", "")).strip()
    t = Trace(reqs, tasks, find_tests(root), commits(root, since), releases(root))
    known = {r.id for r in reqs}
    task_ids = {task.id for task in tasks}

    for task in tasks:
        where = f"TASKS.md:{task.line}"
        if task.req_field is None:
            t.problems.append(
                Problem(
                    where,
                    f"{task.id} has no Req: line (Req: REQ-012, or "
                    "Req: none — <why: tooling, refactor, docs>)",
                )
            )
        elif not task.reqs and not re.match(r"none\b\s*[—–:-]\s*\S", task.req_field, re.I):
            t.problems.append(
                Problem(
                    where,
                    f"{task.id}: Req: names no requirement; write "
                    "'Req: none — <reason>' if none applies",
                )
            )
        for rid in task.reqs:
            if rid not in known:
                t.problems.append(
                    Problem(where, f"{task.id} names {rid}, which isn't in REQUIREMENTS.md")
                )
    for ref in t.tests:
        for rid in ref.reqs:
            if rid not in known:
                t.problems.append(
                    Problem(ref.where, f"names {rid}, which isn't in REQUIREMENTS.md")
                )
    children = defaultdict(list)
    for r in reqs:
        if r.parent and r.state in ACTIVE:
            children[r.parent].append(r.id)
    for r in reqs:
        where = f"REQUIREMENTS.md:{r.line}"
        mine = t.tasks_for(r.id)
        tested = bool(t.tests_for(r.id))
        if r.prefix in ("BR", "SR") and children[r.id]:
            pass  # met through the approved requirements beneath it
        elif r.prefix in ("BR", "SR") and r.state in ACTIVE and not (mine and tested):
            t.problems.append(
                Problem(
                    where,
                    f"{r.id} is {r.state} but nothing traces to it: "
                    "no approved requirement names it as Parent, and it has "
                    "no task and test of its own",
                )
            )
        else:
            if r.state in ACTIVE and not mine:
                t.problems.append(
                    Problem(where, f"{r.id} is {r.state} but no task names it (Req: in TASKS.md)")
                )
            if r.state in ACTIVE and not tested:
                t.problems.append(Problem(where, f"{r.id} is {r.state} but no test names it"))
        if r.state in BUILT and mine and not any(task.done for task in mine):
            t.problems.append(
                Problem(
                    where,
                    f"{r.id} is {r.state} but none of its tasks "
                    f"({', '.join(task.id for task in mine)}) is done",
                )
            )
        if r.state == "released" and not t.shipped.get(r.id):
            t.problems.append(
                Problem(
                    where, f"{r.id} is released but no release record in docs/releases/ lists it"
                )
            )
    for sha, merge, subject in t.history:
        if merge:
            continue
        named = re.findall(rf"\b{TASK_ID}\b", subject)
        if not named and pipeline_record(root, sha):
            continue
        if not named:
            t.problems.append(
                Problem(
                    f"commit {sha[:7]}", f"{subject!r} names no task (e.g. 'feat(api): T031 …')"
                )
            )
        for task_id in named:
            if task_id not in task_ids:
                t.problems.append(
                    Problem(f"commit {sha[:7]}", f"names {task_id}, which isn't in TASKS.md")
                )
    return t


# The release pipeline commits its own records: they carry the release's tasks, not one of theirs.
RECORD_PATHS = ("docs/releases/", "docs/ops/incidents/", "docs/ops/metrics.md")


def pipeline_record(root: Path, sha: str) -> bool:
    """True when a commit only changes release records and incident files."""
    paths = git(root, "show", "--name-only", "--format=", sha).stdout.split()
    return bool(paths) and all(p.startswith(RECORD_PATHS) for p in paths)


def matrix(t: Trace, head: str) -> str:
    rows = [
        "# Requirements traceability matrix",
        "",
        f"Generated by `scripts/realm/realm trace --write` at commit {head[:7]}. Don't edit "
        "it: it's rebuilt from REQUIREMENTS.md, TASKS.md, the tests, the git history and "
        "docs/releases/.",
        "",
        "| Requirement | State | Tasks | Commits | Tests | Releases |",
        "|---|---|---|---|---|---|",
    ]
    ordered = sorted(t.reqs, key=lambda r: (ORDER.index(r.prefix), r.id))
    for r in ordered:
        tasks = t.tasks_for(r.id)
        cells = [
            f"{r.id} {r.title}",
            r.state or "?",
            ", ".join(f"{task.id}{' ✓' if task.done else ''}" for task in tasks) or "—",
            ", ".join(sha for task in tasks for sha in t.commits_for(task.id)) or "—",
            "<br>".join(t.tests_for(r.id)) or "—",
            ", ".join(t.shipped.get(r.id, [])) or "—",
        ]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(rows) + "\n"


def cmd_trace(root: Path, config: dict, write: bool) -> int:
    t = trace(root, config)
    for p in t.problems:
        print(f"!! {p}")
    if write:
        head = git(root, "rev-parse", "HEAD").stdout.strip() or "(no commits)"
        out = root / "docs" / "rtm.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(matrix(t, head), encoding="utf-8")
        print(f"   wrote {out.relative_to(root)}")
    active = sum(r.state in ACTIVE for r in t.reqs)
    print(
        f"   trace: {len(t.reqs)} requirement(s) ({active} approved or later), "
        f"{len(t.tasks)} task(s), {len([c for c in t.history if not c[1]])} commit(s), "
        f"{len(t.tests)} test reference(s); {len(t.problems)} broken link(s)"
    )
    return 1 if t.problems else 0


# ---------------------------------------------------------------- adr-check ---
ADR_FILE = re.compile(r"(\d{4})-[a-z0-9][a-z0-9-]*\.md")
ADR_STATUS = re.compile(r"(proposed|accepted|rejected|deprecated|superseded by (ADR-\d{4}))", re.I)
ADR_SECTIONS = ("Context", "Options considered", "Decision", "Consequences")
DECIDED = ("accepted", "deprecated", "superseded")  # frozen: only the Status line may change


@dataclass
class Adr:
    number: str
    rel: str
    status: str
    superseded_by: str | None
    text: str


def adr_status(text: str) -> tuple[str, str | None]:
    """('accepted', None), ('superseded', 'ADR-0007'), or ('', None) when there's no valid one."""
    m = re.search(r"^- Status:\s*(.+?)\s*$", text, flags=re.M)
    s = ADR_STATUS.fullmatch(m.group(1).strip()) if m else None
    if not s:
        return "", None
    word = s.group(1).split()[0].lower()
    return word, s.group(2).upper() if s.group(2) else None


def frozen_text(text: str) -> str:
    """An ADR without its Status line: the part that may never change once it's decided."""
    lines = [
        line.rstrip()
        for line in text.replace("\r\n", "\n").split("\n")
        if not line.startswith("- Status:")
    ]
    return "\n".join(lines).strip()


def file_history(root: Path, rel: str) -> list[tuple[str, str]]:
    """(commit, the file's path in it) for every commit that touched it, oldest first.

    It follows renames but stops at a copy: a new ADR started from a copy of an older one has
    its own history, which begins where the copy was made."""
    out = git(root, "log", "--follow", "--format=%x00%H", "--name-status", "--", rel).stdout
    history = []
    for chunk in out.split("\0")[1:]:
        lines = [line for line in chunk.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        status, *paths = lines[-1].split("\t")
        history.append((lines[0], paths[-1]))
        if status.startswith(("A", "C")):
            break
    return list(reversed(history))


def show(root: Path, sha: str, path: str) -> str | None:
    r = git(root, "show", f"{sha}:{path}")
    return r.stdout if r.returncode == 0 else None


def check_adrs(root: Path) -> tuple[list[Adr], list[Problem]]:
    folder = root / "docs" / "adr"
    adrs: list[Adr] = []
    problems: list[Problem] = []
    paths = sorted(folder.glob("*.md")) if folder.is_dir() else []
    for path in paths:
        if path.name in ("0000-template.md", "README.md"):
            continue
        rel = path.relative_to(root).as_posix()
        name = ADR_FILE.fullmatch(path.name)
        if not name:
            problems.append(Problem(rel, "name ADRs NNNN-short-title.md (four digits, lowercase)"))
            continue
        text = path.read_text(encoding="utf-8")
        head = re.search(r"^# ADR-(\d{4})\s*[—–-]\s*\S", text, flags=re.M)
        if not head or head.group(1) != name.group(1):
            problems.append(
                Problem(rel, f"the heading must read '# ADR-{name.group(1)} — <title>'")
            )
        status, by = adr_status(text)
        if not status:
            problems.append(
                Problem(
                    rel,
                    "Status must be proposed, accepted, rejected, deprecated "
                    "or 'superseded by ADR-nnnn'",
                )
            )
        if not re.search(r"^- Date:\s*\d{4}-\d{2}-\d{2}\b", text, flags=re.M):
            problems.append(Problem(rel, "no Date: YYYY-MM-DD"))
        if status in DECIDED:
            for heading in ADR_SECTIONS:
                body = section(text, heading)
                if body is None or not blank_out(body).strip():
                    problems.append(Problem(rel, f"a decided ADR needs its '{heading}' section"))
        adrs.append(Adr(name.group(1), rel, status, by, text))

    numbers = [a.number for a in adrs]
    for number in sorted({n for n in numbers if numbers.count(n) > 1}):
        problems.append(Problem("docs/adr", f"ADR-{number} is used by more than one file"))
    known = {f"ADR-{a.number}": a for a in adrs}
    for a in adrs:
        if a.superseded_by:
            newer = known.get(a.superseded_by)
            if newer is None:
                problems.append(
                    Problem(a.rel, f"superseded by {a.superseded_by}, which doesn't exist")
                )
            elif newer.number <= a.number:
                problems.append(
                    Problem(
                        a.rel,
                        f"superseded by {a.superseded_by}, which is older: "
                        "a newer ADR replaces an older one",
                    )
                )
            elif newer.status != "accepted":
                problems.append(
                    Problem(a.rel, f"superseded by {a.superseded_by}, which isn't accepted")
                )
        problems += frozen(root, a)
    problems += deleted(root)
    return adrs, problems


def frozen(root: Path, adr: Adr) -> list[Problem]:
    """Once an ADR was committed as accepted, only its Status line may change."""
    for sha, path in file_history(root, adr.rel):
        old = show(root, sha, path)
        if old is not None and adr_status(old)[0] == "accepted":
            if adr.status not in DECIDED:
                return [
                    Problem(
                        adr.rel,
                        f"was accepted in {sha[:7]}; a decided ADR can only "
                        "become deprecated or superseded, not " + (adr.status or "blank"),
                    )
                ]
            if frozen_text(old) != frozen_text(adr.text):
                return [
                    Problem(
                        adr.rel,
                        f"was accepted in {sha[:7]} and its text has changed "
                        "since. Only the Status line may change: write a new ADR that "
                        "supersedes it",
                    )
                ]
            return []
    return []


def deleted(root: Path) -> list[Problem]:
    out = git(
        root, "log", "--diff-filter=D", "--format=%x00%H", "--name-only", "--", "docs/adr"
    ).stdout
    problems = []
    for chunk in out.split("\0")[1:]:
        lines = [line for line in chunk.splitlines() if line.strip()]
        for path in lines[1:]:
            if Path(path).name == "0000-template.md" or (root / path).exists():
                continue
            old = show(root, f"{lines[0]}^", path)
            if old is not None and adr_status(old)[0] in DECIDED:
                problems.append(
                    Problem(
                        path,
                        f"a decided ADR was deleted in {lines[0][:7]}. "
                        "ADRs stay: supersede or deprecate it instead",
                    )
                )
    return problems


def cmd_adr_check(root: Path) -> int:
    adrs, problems = check_adrs(root)
    for p in problems:
        print(f"!! {p}")
    decided = sum(a.status in DECIDED for a in adrs)
    print(
        f"   adr-check: {len(adrs)} ADR(s), {decided} decided and frozen; "
        f"{len(problems)} problem(s)"
    )
    return 1 if problems else 0


# ------------------------------------------------------------- design-check ---
STRIDE = (
    "spoofing",
    "tampering",
    "repudiation",
    "information disclosure",
    "denial of service",
    "elevation of privilege",
)
PLACEHOLDER = re.compile(r"<(?!/?[a-z]+\s*/?>)[^<>\n]+>")
C4 = (("context.md", "C4Context", 1), ("containers.md", "C4Container", 2))


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def table(body: str) -> list[list[str]]:
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("|") and not re.fullmatch(r"\|?[\s:|-]+\|?", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def check_threats(rel: str, text: str) -> list[Problem]:
    m = re.search(
        r"^(#{2,3})\s+[^\n]*\bthreats\b[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)",
        text,
        flags=re.S | re.M | re.I,
    )
    if not m:
        return [
            Problem(
                rel,
                "no Threats section: add docs/security/threats.template.md's "
                "STRIDE table, or 'None, because <reason>'",
            )
        ]
    body = strip_comments(m.group(2))
    if re.search(r"^\s*none,?\s+because\s+\S+\s+\S+\s+\S+", body, flags=re.M | re.I):
        return []
    rows = table(body)
    if len(rows) < 2:
        return [
            Problem(
                rel,
                "the Threats section lists no threats: add a row per threat, or "
                "write 'None, because <reason>'",
            )
        ]
    header = [c.lower() for c in rows[0]]
    stride = next((i for i, c in enumerate(header) if "stride" in c), None)
    mitigation = next((i for i, c in enumerate(header) if "mitigation" in c), None)
    if stride is None or mitigation is None:
        return [Problem(rel, "the threats table needs STRIDE and Mitigation columns")]
    problems = []
    for n, row in enumerate(rows[1:], 1):
        cells = row + [""] * len(header)
        category = cells[stride].lower()
        if not any(s in category for s in STRIDE):
            problems.append(
                Problem(
                    rel,
                    f"threat {n}: STRIDE category {category or 'missing'} "
                    "(Spoofing, Tampering, Repudiation, Information disclosure, "
                    "Denial of service, Elevation of privilege)",
                )
            )
        if not cells[mitigation]:
            problems.append(Problem(rel, f"threat {n} has no mitigation"))
    return problems


def cmd_design_check(root: Path) -> int:
    problems: list[Problem] = []
    text = (
        (root / "REQUIREMENTS.md").read_text(encoding="utf-8")
        if (root / "REQUIREMENTS.md").exists()
        else ""
    )
    started = any(r.state in ACTIVE for r in parse_requirements(text)[0])
    for name, kind, level in C4:
        path = root / "docs" / "architecture" / name
        rel = path.relative_to(root).as_posix()
        if not path.exists():
            problems.append(
                Problem(
                    rel,
                    f"missing: the C4 level-{level} diagram is required "
                    f"(start from docs/architecture/{name[:-3]}.template.md)",
                )
            )
            continue
        diagram = path.read_text(encoding="utf-8")
        if not re.search(rf"^```mermaid\s*\n\s*{kind}\b", diagram, flags=re.M):
            problems.append(Problem(rel, f"needs a ```mermaid block starting with {kind}"))
        placeholder = PLACEHOLDER.search(strip_comments(diagram))
        if started and placeholder:
            problems.append(
                Problem(
                    rel,
                    "requirements are approved, but the diagram still has placeholders: "
                    + placeholder.group(0),
                )
            )
    designs = (
        sorted((root / "docs" / "design").glob("*.md"))
        if (root / "docs" / "design").is_dir()
        else []
    )
    for path in designs:
        if path.name == "README.md" or "template" in path.name:
            continue
        problems += check_threats(
            path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")
        )
    for p in problems:
        print(f"!! {p}")
    print(
        f"   design-check: C4 levels 1-2, and threats in {len(designs)} design doc(s); "
        f"{len(problems)} problem(s)"
    )
    return 1 if problems else 0


# -------------------------------------------------------------------- gates ---
STAGES = ("Concept", "Development", "Release", "Operation", "Retirement")


@dataclass
class GateEntry:
    stage: str
    date: str
    evidence: str
    signed: str


def parse_gates(text: str) -> tuple[dict[str, GateEntry | None], list[Problem]]:
    """Each stage's passing entry (or None), and what's malformed."""
    found: dict[str, GateEntry | None] = {}
    problems: list[Problem] = []
    for stage in STAGES:
        body = section(text, stage)
        if body is None:
            problems.append(Problem("GATES.md", f"no '## {stage}' section"))
            continue
        entries = re.findall(r"^- Passed:\s*(.*)$", blank_out(body), flags=re.M)
        found[stage] = None
        if len(entries) > 1:
            problems.append(
                Problem(
                    "GATES.md", f"{stage} has {len(entries)} Passed entries; a gate passes once"
                )
            )
        if entries:
            parts = [p.strip() for p in re.split(r"\s+·\s+", entries[0].strip())]
            fields = {"passed": parts[0]}
            for part in parts[1:]:
                key, _, value = part.partition(":")
                fields[key.strip().lower()] = value.strip()
            found[stage] = GateEntry(
                stage, fields["passed"], fields.get("evidence", ""), fields.get("signed", "")
            )
    return found, problems


def check_gates(root: Path, tier: str) -> list[Problem]:
    path = root / "GATES.md"
    if not path.exists():
        return [Problem("GATES.md", "missing: a realm project records its stage gates there")]
    gates, problems = parse_gates(path.read_text(encoding="utf-8"))
    last_date = ""
    for n, stage in enumerate(STAGES):
        entry = gates.get(stage)
        if entry is None:
            continue
        dt_ok = is_date(entry.date)
        if not dt_ok:
            problems.append(Problem("GATES.md", f"{stage}: Passed needs a date, YYYY-MM-DD"))
        if not entry.evidence or re.search(r"<[^>]+>|…", entry.evidence):
            problems.append(Problem("GATES.md", f"{stage}: say what the Evidence is"))
        if tier == "assured" and (not entry.signed or re.search(r"<[^>]+>|…", entry.signed)):
            problems.append(
                Problem(
                    "GATES.md",
                    f"{stage}: the assured tier needs the entry Signed by whoever decided",
                )
            )
        earlier = [s for s in STAGES[:n] if gates.get(s) is None]
        if earlier:
            problems.append(Problem("GATES.md", f"{stage} passed before {earlier[0]}"))
        if dt_ok and entry.date < last_date:
            problems.append(Problem("GATES.md", f"{stage} is dated before the gate before it"))
        last_date = max(last_date, entry.date if dt_ok else "")
    return problems


def is_date(text: str) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)) and bool(date.fromisoformat(text))
    except ValueError:
        return False


def gate_passed(root: Path, stage: str) -> bool:
    path = root / "GATES.md"
    if not path.exists():
        return False
    gates, _ = parse_gates(path.read_text(encoding="utf-8"))
    return gates.get(stage) is not None


def cmd_gates(root: Path, config: dict) -> int:
    problems = check_gates(root, config["realm"]["tier"])
    for p in problems:
        print(f"!! {p}")
    passed = []
    if (root / "GATES.md").exists():
        gates, _ = parse_gates((root / "GATES.md").read_text(encoding="utf-8"))
        passed = [s for s in STAGES if gates.get(s)]
    print(f"   gates: passed {', '.join(passed) or 'none yet'}; {len(problems)} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------- incidents ---
INC_FILE = re.compile(r"INC-(\d{4})\.md")


def check_incidents(root: Path) -> tuple[int, int, list[Problem]]:
    """(open, closed, problems): an incident closes only with a postmortem and a named change."""
    folder = root / "docs" / "ops" / "incidents"
    problems: list[Problem] = []
    counts = {"open": 0, "closed": 0}
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        name = INC_FILE.fullmatch(path.name)
        if not name:
            problems.append(Problem(rel, "name incidents INC-nnnn.md (four digits)"))
            continue
        text = path.read_text(encoding="utf-8")
        if not re.search(rf"^# INC-{name.group(1)}\s*[—–-]\s*\S", text, flags=re.M):
            problems.append(
                Problem(
                    rel, f"the heading must read '# INC-{name.group(1)} — <what users noticed>'"
                )
            )
        status = re.search(r"^- Status:\s*(\w+)", text, flags=re.M)
        state = status.group(1).lower() if status else ""
        if state not in counts:
            problems.append(Problem(rel, "Status is open or closed"))
            continue
        counts[state] += 1
        if state == "open":
            continue
        opened = re.search(r"^- Opened:(.*)$", text, flags=re.M)
        if not opened or not re.search(r"Closed:\s*\d{4}-\d{2}-\d{2}", opened.group(1)):
            problems.append(
                Problem(rel, "closed, but the Opened line has no '· Closed: YYYY-MM-DD HH:MM UTC'")
            )
        if not blank_out(section(text, "Postmortem") or "").strip():
            problems.append(Problem(rel, "closed without a postmortem"))
        change = blank_out(section(text, "The change that stops it recurring") or "")
        shas = re.findall(r"\b[0-9a-f]{7,40}\b", change)
        prs = re.findall(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", change)
        known = [s for s in shas if git(root, "cat-file", "-e", f"{s}^{{commit}}").returncode == 0]
        if not (known or prs):
            problems.append(
                Problem(
                    rel,
                    "closed without the change that stops it recurring: "
                    "name its commit (one this repo has) or its PR's URL",
                )
            )
    return counts["open"], counts["closed"], problems


def cmd_incidents(root: Path) -> int:
    opened, closed, problems = check_incidents(root)
    for p in problems:
        print(f"!! {p}")
    print(f"   incidents: {opened} open, {closed} closed; {len(problems)} problem(s)")
    return 1 if problems else 0


# ------------------------------------------------------------ infrastructure ---
# checkov honours `#checkov:skip=CKV_AWS_338` with no reason at all; the gate doesn't (§14.6).
CHECKOV_SKIP = re.compile(r"(?:#|//)\s*checkov:skip=([^\s:]+)(?::(.*))?")


def checkov_skips(root: Path) -> tuple[int, list[Problem]]:
    """How many inline checkov skips infra/ has, and each one that doesn't say why."""
    count, problems = 0, []
    for path in sorted((root / "infra").rglob("*.tf")):
        if ".terraform" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = CHECKOV_SKIP.search(line)
            if not m:
                continue
            count += 1
            reason = (m.group(2) or "").strip()
            if len(reason) < 10:
                problems.append(
                    Problem(
                        f"{rel}:{n}",
                        f"the skip of {m.group(1)} needs its reason: "
                        f"#checkov:skip={m.group(1)}:<why this check doesn't apply here>",
                    )
                )
    return count, problems


def cmd_checkov_skips(root: Path) -> int:
    count, problems = checkov_skips(root)
    for p in problems:
        print(f"!! {p}")
    print(f"   checkov skips: {count} in infra/; {len(problems)} without a reason")
    return 1 if problems else 0


# --------------------------------------------------------------------- main ---
def cmd_release(root: Path, config: dict, args: list[str]) -> int:
    """`realm release ...`: the release pipeline's helpers (release.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release  # imported here: only the release pipeline needs it

    tasks_file = root / "TASKS.md"
    tasks = parse_tasks(tasks_file.read_text(encoding="utf-8")) if tasks_file.exists() else []
    try:
        return release.cli(root, config, args, {t.id: t.reqs for t in tasks}, git)
    except release.ReleaseError as e:
        print(f"!! release: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="realm", description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("req-lint", help="check REQUIREMENTS.md")
    tr = sub.add_parser("trace", help="check every requirement's links")
    tr.add_argument("--write", action="store_true", help="also write docs/rtm.md")
    sub.add_parser("adr-check", help="check the ADRs; a decided one's text is frozen")
    sub.add_parser("design-check", help="C4 levels 1-2, and a threats section per design doc")
    sub.add_parser("gates", help="check GATES.md")
    sub.add_parser("incidents", help="check docs/ops/incidents/")
    sub.add_parser("checkov-skips", help="every inline checkov skip in infra/ says why")
    gp = sub.add_parser("gate-passed", help="exit 0 if that stage's gate has passed")
    gp.add_argument("stage", choices=STAGES)
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["eol"], ["dora"], ["upstream"]):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ops  # imported here: only the scheduled checks need it

        try:
            return ops.cli(repo_root(), argv)
        except (RealmError, ops.OpsError) as e:
            print(f"!! realm: {e}")
            return 1
    if argv[:1] in (["release"], ["railway"], ["aws"]):
        try:
            root = repo_root()
            config = load_config(root)
        except RealmError as e:
            print(f"!! realm: {e}")
            return 1
        if argv[0] == "release":
            return cmd_release(root, config, argv[1:])
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        if argv[0] == "aws":
            import aws  # imported here: only the aws adapter needs it

            return aws.cli(config, argv[1:])
        import railway  # imported here: only the railway adapter needs it

        return railway.cli(config, argv[1:])
    args = parser.parse_args(argv)
    try:
        root = repo_root()
        config = load_config(root)
        if args.command == "req-lint":
            return cmd_req_lint(root, config)
        if args.command == "adr-check":
            return cmd_adr_check(root)
        if args.command == "design-check":
            return cmd_design_check(root)
        if args.command == "gates":
            return cmd_gates(root, config)
        if args.command == "incidents":
            return cmd_incidents(root)
        if args.command == "checkov-skips":
            return cmd_checkov_skips(root)
        if args.command == "gate-passed":
            return 0 if gate_passed(root, args.stage) else 1
        return cmd_trace(root, config, args.write)
    except RealmError as e:
        print(f"!! realm: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
