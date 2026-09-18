"""realm eol | dora | upstream: the scheduled checks (DESIGN.md §3 rows 13 and 14).

    realm eol [--warn-days N]        every runtime the project uses, against endoflife.date:
                                     fails when one is past, or within N days of, its end of life
    realm dora [--month YYYY-MM] [--write]
                                     the month's delivery and maintenance metrics, from the release
                                     records, the incidents and git; --write puts them in
                                     docs/ops/metrics.md
    realm upstream                   the Secret Realm kit only: how many Cultivation commits it
                                     hasn't merged yet; fails when it's behind

The realm-scheduled workflow runs eol weekly (with the gate) and dora monthly. Standard library
only; Python 3.11+.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

EOL_API = "https://endoflife.date/api/v1/products/{product}/releases/{cycle}"
# Base images and the endoflife.date product that tracks them: image -> (product, digits kept)
IMAGES = {
    "python": ("python", 2),
    "node": ("nodejs", 1),
    "postgres": ("postgresql", 1),
    "redis": ("redis", 2),
    "nginx": ("nginx", 2),
    "golang": ("go", 2),
    "eclipse-temurin": ("eclipse-temurin", 1),
    "ruby": ("ruby", 2),
    "php": ("php", 2),
    "debian": ("debian", 1),
    "ubuntu": ("ubuntu", 2),
    "alpine": ("alpine", 2),
}
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", ".realm", "__pycache__"}


class OpsError(Exception):
    """A scheduled check that can't run. Printed without a traceback."""


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return r.stdout


def files(root: Path, name: str) -> list[Path]:
    return [p for p in root.rglob(name) if not SKIP_DIRS & set(p.relative_to(root).parts[:-1])]


# ---------------------------------------------------------------------- eol ---
def cycle(version: str, digits: int) -> str:
    parts = re.findall(r"\d+", version)
    return ".".join(parts[:digits]) if len(parts) >= digits else ""


def runtimes(root: Path) -> dict[tuple[str, str], list[str]]:
    """(product, release cycle) -> where it's used."""
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in files(root, ".python-version"):
        c = cycle(path.read_text().strip(), 2)
        if c:
            found[("python", c)].append(path.relative_to(root).as_posix())
    for path in files(root, "Dockerfile*"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*FROM\s+(?:--\S+\s+)*([\w./-]+):([\w.-]+)", line, flags=re.I)
            if not m:
                continue
            image = m.group(1).split("/")[-1]
            if image in IMAGES:
                product, digits = IMAGES[image]
                c = cycle(m.group(2), digits)
                if c:
                    found[(product, c)].append(f"{path.relative_to(root).as_posix()}:{n}")
    for path in files(root, "package.json"):
        engines = json.loads(path.read_text(encoding="utf-8")).get("engines", {})
        c = cycle(str(engines.get("node", "")), 1)
        if c:
            found[("nodejs", c)].append(path.relative_to(root).as_posix())
    return found


def web_url(url: str) -> str:
    """Only http(s): an override pointing urllib at a file:// URL would read local files."""
    if urllib.parse.urlsplit(url).scheme not in ("https", "http"):
        raise OpsError(f"refusing a non-web URL: {url}")
    return url


def eol_date(product: str, release: str) -> dt.date | None:
    url = web_url(os.environ.get("REALM_EOL_API", EOL_API).format(product=product, cycle=release))
    try:
        # web_url() allowed http(s) only; Semgrep can't see that, hence the nosemgrep.
        with urllib.request.urlopen(url, timeout=20) as response:  # nosemgrep
            result = json.load(response)["result"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise OpsError(f"endoflife.date doesn't know {product} {release}") from e
        raise OpsError(f"endoflife.date answered {e.code} for {product} {release}") from e
    except urllib.error.URLError as e:
        raise OpsError(f"couldn't reach endoflife.date: {e.reason}") from e
    value = result.get("eolFrom")
    return dt.date.fromisoformat(value) if value else None


def cmd_eol(root: Path, warn_days: int, today: dt.date) -> int:
    used = runtimes(root)
    if not used:
        print("   eol: no runtime found (.python-version, Dockerfile FROM, package.json engines)")
        return 0
    problems = 0
    for (product, release), where in sorted(used.items()):
        end = eol_date(product, release)
        if end is None:
            print(f"   {product} {release}: no end of life announced ({', '.join(where)})")
        elif end <= today:
            print(f"!! {product} {release} reached its end of life on {end}: {', '.join(where)}")
            problems += 1
        elif (end - today).days <= warn_days:
            print(
                f"!! {product} {release} reaches its end of life on {end}, in "
                f"{(end - today).days} days: plan the upgrade ({', '.join(where)})"
            )
            problems += 1
        else:
            print(f"   {product} {release}: supported until {end}")
    return 1 if problems else 0


# --------------------------------------------------------------------- dora ---
STAMP = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC"
KINDS = {
    "fix": "corrective",
    "chore(deps)": "adaptive",
    "build": "adaptive",
    "refactor": "perfective",
    "perf": "perfective",
    "test": "preventive",
    "chore(harden)": "preventive",
    "feat": "new capability",
}


def parse_stamp(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=dt.UTC)


def in_month(when: dt.datetime, month: str) -> bool:
    return when.strftime("%Y-%m") == month


def promotions(root: Path, month: str) -> list[dict]:
    """Every promotion the records show in the month: version, when, commit, failed or not."""
    folder = root / "docs" / "releases"
    found = []
    for path in sorted(folder.glob("v*.md")) if folder.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        m = re.search(rf"^- Promoted(, then rolled back)?:\s*{STAMP}", text, flags=re.M)
        if not m:
            continue
        when = parse_stamp(m.group(2))
        if in_month(when, month):
            commit = re.search(r"^- Commit:\s*([0-9a-f]{40})", text, flags=re.M)
            previous = re.search(r"^- Previous:\s*(v\d+\.\d+\.\d+)", text, flags=re.M)
            found.append(
                {
                    "version": path.stem,
                    "when": when,
                    "failed": bool(m.group(1)),
                    "commit": commit.group(1) if commit else "",
                    "previous": previous.group(1) if previous else "",
                }
            )
    return found


def incidents(root: Path) -> list[dict]:
    folder = root / "docs" / "ops" / "incidents"
    found = []
    for path in sorted(folder.glob("INC-*.md")) if folder.is_dir() else []:
        line = re.search(r"^- Opened:(.*)$", path.read_text(encoding="utf-8"), flags=re.M)
        if not line:
            continue
        opened = re.search(STAMP, line.group(1))
        closed = re.search(rf"Closed:\s*{STAMP}", line.group(1))
        release = re.search(r"Release:\s*(v\d+\.\d+\.\d+)", line.group(1))
        found.append(
            {
                "opened": parse_stamp(opened.group(1)) if opened else None,
                "closed": parse_stamp(closed.group(1)) if closed else None,
                "release": release.group(1) if release else "",
            }
        )
    return found


def commit_times(root: Path, since: str, until: str) -> list[dt.datetime]:
    rng = f"{since}..{until}" if since else until
    return [
        dt.datetime.fromtimestamp(int(t), dt.UTC)
        for t in git(root, "log", "--no-merges", "--format=%ct", rng).split()
    ]


def midnight(day: dt.date) -> str:
    """A day's start, explicitly: a bare date in --since means that date at the current time."""
    return f"{day.isoformat()}T00:00:00Z"


def churn(root: Path, start: dt.date, end: dt.date) -> tuple[int, int]:
    """(lines added in the month, of those, deleted again within 14 days of being added).

    An approximation of 14-day churn from `git log --numstat`: a deletion in a file counts
    against the lines added to that file in the 14 days before it."""
    log = git(
        root,
        "log",
        "--no-merges",
        "--reverse",
        "--numstat",
        "--format=@%ct",
        f"--since={midnight(start - dt.timedelta(days=14))}",
        f"--until={midnight(end + dt.timedelta(days=1))}",
    )
    recent: dict[str, list[tuple[dt.datetime, int]]] = defaultdict(list)
    added = churned = 0
    when = dt.datetime.min.replace(tzinfo=dt.UTC)
    for line in log.splitlines():
        if line.startswith("@"):
            when = dt.datetime.fromtimestamp(int(line[1:]), dt.UTC)
            continue
        cells = line.split("\t")
        if len(cells) != 3 or not cells[0].isdigit():
            continue  # a binary file
        plus, minus, path = int(cells[0]), int(cells[1]), cells[2]
        window = [(t, n) for t, n in recent[path] if (when - t).days < 14]
        if start <= when.date() <= end:
            added += plus
            churned += min(minus, sum(n for _, n in window))
        recent[path] = [*window, (when, plus)]
    return added, churned


def kinds(root: Path, start: dt.date, end: dt.date) -> Counter:
    subjects = git(
        root,
        "log",
        "--no-merges",
        "--format=%s",
        f"--since={midnight(start)}",
        f"--until={midnight(end + dt.timedelta(days=1))}",
    ).splitlines()
    counted: Counter = Counter()
    for subject in subjects:
        m = re.match(r"(\w+)(\([^)]*\))?!?:", subject)
        if not m:
            counted["other"] += 1
            continue
        scoped = f"{m.group(1)}{m.group(2) or ''}"
        counted[KINDS.get(scoped, KINDS.get(m.group(1), "other"))] += 1
    return counted


def hours(delta: dt.timedelta) -> str:
    h = delta.total_seconds() / 3600
    return f"{h / 24:.1f} days" if h >= 48 else f"{h:.1f} h"


def dora(root: Path, month: str) -> str:
    start = dt.date.fromisoformat(f"{month}-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    shipped = promotions(root, month)
    records = (
        {p.stem: p.read_text(encoding="utf-8") for p in (root / "docs" / "releases").glob("v*.md")}
        if (root / "docs" / "releases").is_dir()
        else {}
    )
    leads = []
    for p in shipped:
        before = re.search(r"^- Commit:\s*([0-9a-f]{40})", records.get(p["previous"], ""), re.M)
        times = commit_times(root, before.group(1) if before else "", p["commit"] or "HEAD")
        leads += [p["when"] - t for t in times if t <= p["when"]]  # skewed clocks aside
    all_incidents = incidents(root)
    failed = [
        p
        for p in shipped
        if p["failed"] or any(i["release"] == p["version"] for i in all_incidents)
    ]
    restored = [
        i["closed"] - i["opened"]
        for i in all_incidents
        if i["opened"] and i["closed"] and in_month(i["closed"], month)
    ]
    added, churned = churn(root, start, end)
    counted = kinds(root, start, end)
    rows = [
        (
            "Deployment frequency",
            f"{len(shipped)} promotion(s)",
            "promotions in the release records",
        ),
        (
            "Lead time for changes",
            f"{hours(statistics.median(leads))} (median)" if leads else "no changes shipped",
            "each shipped commit's time to its promotion",
        ),
        (
            "Change failure rate",
            f"{100 * len(failed) // len(shipped)}% ({len(failed)} of {len(shipped)})"
            if shipped
            else "no promotions",
            "promotions rolled back, or named by an incident",
        ),
        (
            "Time to restore",
            f"{hours(statistics.median(restored))} (median)" if restored else "no incidents closed",
            "incidents' Opened to Closed",
        ),
        (
            "14-day churn",
            f"{100 * churned / added:.1f}% ({churned} of {added} lines)"
            if added
            else "no lines added",
            "lines deleted within 14 days of being added",
        ),
        (
            "Maintenance",
            " · ".join(f"{k} {n}" for k, n in counted.most_common()) or "no commits",
            "commit types (DESIGN.md §7.8)",
        ),
    ]
    table = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    return f"## {month}\n\n| Measure | Value | How |\n|---|---|---|\n{table}\n"


HEADER = """# Delivery and maintenance metrics

Written by `scripts/realm/realm dora --write`, which the realm-scheduled workflow runs on the first
of each month. DORA's four keys come from the release records and the incidents; churn and the
kinds of work from git. A rising share of corrective work is the early warning.

"""


def write_metrics(root: Path, month: str, section: str) -> Path:
    path = root / "docs" / "ops" / "metrics.md"
    text = path.read_text(encoding="utf-8") if path.exists() else HEADER
    pattern = rf"^## {re.escape(month)}\n.*?(?=^## |\Z)"
    if re.search(pattern, text, flags=re.S | re.M):
        text = re.sub(pattern, lambda _: section + "\n", text, count=1, flags=re.S | re.M)
    else:
        first = re.search(r"^## ", text, flags=re.M)
        at = first.start() if first else len(text)
        text = text[:at] + section + "\n" + text[at:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------- upstream ---
def cmd_upstream(root: Path) -> int:
    remotes = git(root, "remote").split()
    if "upstream" not in remotes:
        raise OpsError("no upstream remote: only the Secret Realm kit tracks Cultivation")
    fetched = subprocess.run(
        ["git", "fetch", "-q", "upstream", "main"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0:
        raise OpsError(f"couldn't fetch Cultivation: {fetched.stderr.strip()}")
    behind = int(git(root, "rev-list", "--count", "HEAD..upstream/main").strip() or 0)
    if behind:
        subjects = git(root, "log", "--format=  %h %s", "HEAD..upstream/main").rstrip()
        print(f"!! {behind} Cultivation commit(s) not merged yet:\n{subjects}")
        print("   Merge them: git fetch upstream && git merge upstream/main (on a branch, by PR)")
        return 1
    print("   upstream: up to date with Cultivation")
    return 0


# ---------------------------------------------------------------------- cli ---
def previous_month(today: dt.date) -> str:
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def cli(root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="realm")
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("eol")
    e.add_argument("--warn-days", type=int, default=None)
    d = sub.add_parser("dora")
    d.add_argument("--month", default=previous_month(dt.date.today()))
    d.add_argument("--write", action="store_true")
    sub.add_parser("upstream")
    a = parser.parse_args(argv)
    if a.command == "upstream":
        return cmd_upstream(root)
    if a.command == "eol":
        config = (
            tomllib.loads((root / "realm.toml").read_text())
            if (root / "realm.toml").exists()
            else {}
        )
        warn = (
            a.warn_days
            if a.warn_days is not None
            else int(config.get("eol", {}).get("warn_days", 90))
        )
        return cmd_eol(root, warn, dt.date.today())
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        raise OpsError("--month is YYYY-MM")
    section = dora(root, a.month)
    print(section)
    if a.write:
        print(f"   wrote {write_metrics(root, a.month, section).relative_to(root)}")
    return 0
