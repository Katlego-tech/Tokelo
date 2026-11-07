"""realm release: the release pipeline's helpers, called by scripts/realm/release.sh.

    realm release services              one line per [[service]]: name, context, dockerfile,
                                        port, health path, ui, kind (tab-separated; a worker's
                                        missing port and health are -)
    realm release config <key>          a value from realm.toml, e.g. realm.tier
    realm release names                 the [[service]] names, one a line (nothing else checked)
    realm release provenance <version>  write dist/<version>/release.json from the build's results
    realm release perf-env              the secret PERF_ENV's KEY=value lines, checked, for k6
    realm release files-build <version> <service> <n>
                                        build a files service's tree into dist/<version>/
                                        <service>.<n>.tar.gz; print its digest (DESIGN.md §15)
    realm release publish-files <version>
                                        keep each files service's archive and its signature as
                                        assets of the GitHub release on the version's tag
    realm release compose-port <env>    the compose platform: the first local port <env> is
                                        published on ([deploy] staging_port / production_port)
    realm release zap-detail <log> <exit code>
                                        a failed ZAP scan's findings, as one line for the record

The bash script runs the tools; this file holds the rules, so they can be tested (DESIGN.md §5.2,
§7.7). Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = re.compile(r"v\d+\.\d+\.\d+")
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
# A worker has no URL: the adapter's health verb checks it (§14.1). A files service is a built
# file tree, not an image: the host serves it, so it has a URL but no container (§15.1).
KINDS = ("web", "worker", "files")
ENV_KEY = re.compile(r"[A-Z_][A-Z0-9_]*")


class ReleaseError(Exception):
    """A problem that stops the release. Printed without a traceback."""


@dataclass
class Service:
    name: str
    context: str
    dockerfile: str
    port: int | None
    health: str
    ui: bool
    kind: str = "web"
    build: str = ""  # a files service: the command that makes the tree,
    output: str = ""  # the folder it makes,
    include: tuple[str, ...] = ()  # and source:destination paths added to it

    def row(self) -> str:
        # Never an empty cell: bash's read with IFS=$'\t' would merge it with the next one.
        cells = (
            self.name,
            self.context,
            self.dockerfile,
            str(self.port) if self.port else "-",
            self.health or "-",
            "true" if self.ui else "false",
            self.kind,
        )
        return "\t".join(cells)


def check_version(version: str) -> str:
    if not VERSION.fullmatch(version):
        raise ReleaseError(f"a release version looks like v1.4.0, not {version!r}")
    return version


def inside(path: str) -> bool:
    """Whether `path` is a relative path that stays inside the repo, and isn't the repo itself."""
    p = PurePosixPath(path)
    return bool(path) and not p.is_absolute() and ".." not in p.parts and p != PurePosixPath(".")


def files_service(s: dict, name: str) -> Service:
    """A kind = "files" service (DESIGN.md §15.2): what builds its tree, and what the tree holds."""
    if "port" in s:
        raise ReleaseError(f"service {name}: a files service has no port; the host serves it")
    if "context" in s or "dockerfile" in s:
        raise ReleaseError(
            f"service {name}: a files service has no context or dockerfile; it's built by "
            "its build command"
        )
    build = str(s.get("build", "")).strip()
    if not build:
        raise ReleaseError(f"service {name}: needs build, the command that makes its tree")
    output = str(s.get("output", "")).strip().rstrip("/")
    if not output:
        raise ReleaseError(f"service {name}: needs output, the folder its build makes")
    if not inside(output):
        raise ReleaseError(f"service {name}: output must be a folder inside the repo, like out")
    include = s.get("include", [])
    if not isinstance(include, list):
        raise ReleaseError(f'service {name}: include is a list, like ["php/api:api"]')
    for entry in include:
        source, sep, dest = str(entry).partition(":")
        if not sep:
            raise ReleaseError(f"service {name}: include {entry!r}: write it as source:destination")
        if not (inside(source) and inside(dest)):
            raise ReleaseError(
                f"service {name}: include {entry!r}: both paths stay inside the repo and the "
                "tree, and neither is the top"
            )
    health = str(s.get("health", ""))
    if not health.startswith("/"):
        raise ReleaseError(f"service {name}: health must be a path, like /health")
    ui = bool(s.get("ui", False))
    # No context or dockerfile: "-", since bash's read with IFS=$'\t' would merge an empty cell.
    return Service(
        name, "-", "-", None, health, ui, "files", build, output, tuple(map(str, include))
    )


def services(config: dict, root: Path) -> list[Service]:
    found = []
    raw = config.get("service", [])
    if not raw:
        raise ReleaseError("realm.toml declares no [[service]]: nothing to release")
    for n, s in enumerate(raw, 1):
        name = str(s.get("name", ""))
        if not NAME.fullmatch(name):
            raise ReleaseError(f"[[service]] {n}: name must be lowercase letters, digits and -")
        kind = str(s.get("kind", "web"))
        if kind not in KINDS:
            raise ReleaseError(f"service {name}: kind is {kind!r}: use web, worker or files")
        if kind == "files":
            found.append(files_service(s, name))
            continue
        context = str(s.get("context", ""))
        dockerfile = str(s.get("dockerfile", "Dockerfile"))
        if not (root / context / dockerfile).is_file():
            raise ReleaseError(f"service {name}: no {Path(context) / dockerfile}")
        port = s.get("port")
        if (kind == "web" or port is not None) and (
            not isinstance(port, int) or not 0 < port < 65536
        ):
            raise ReleaseError(f"service {name}: port must be a number")
        health = str(s.get("health", ""))
        ui = bool(s.get("ui", False))
        if kind == "worker" and (health or ui):
            raise ReleaseError(
                f"service {name}: a worker has no URL, so no health path and no ui; "
                "the adapter's health verb checks it"
            )
        if kind == "web" and not health.startswith("/"):
            raise ReleaseError(f"service {name}: health must be a path, like /health")
        found.append(Service(name, context, dockerfile, port, health, ui, kind))
    names = [s.name for s in found]
    if len(set(names)) != len(names):
        raise ReleaseError("two [[service]] entries share a name")
    return found


def config_value(config: dict, key: str) -> str:
    node: object = config
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ReleaseError(f"realm.toml has no {key}")
        node = node[part]
    return str(node).lower() if isinstance(node, bool) else str(node)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vulnerabilities(report: Path) -> int:
    """How many known vulnerabilities osv-scanner reported for an image (0 if none)."""
    if not report.exists() or not report.read_text().strip():
        return 0
    data = json.loads(report.read_text())
    return sum(
        len(p.get("vulnerabilities", []))
        for result in data.get("results", [])
        for p in result.get("packages", [])
    )


def provenance(version: str, out: Path, commit: str, epoch: int, config: dict) -> dict:
    """release.json: what was built, from what, how, and whether it was reproducible."""
    rows = [line.split("\t") for line in (out / "build.tsv").read_text().splitlines() if line]
    kinds = {str(s.get("name")): s.get("kind", "web") for s in config.get("service", [])}
    built = []
    for name, image, digest, reproducible, sbom in rows:
        built.append(
            {
                "name": name,
                # A files service's artefact is its archive; "image" names the file (§15.1).
                "artefact": "files" if kinds.get(name) == "files" else "image",
                "image": image,
                "digest": digest,
                "reproducible": reproducible == "yes",
                "sbom": sbom,
                "sbom_sha256": sha256(out / sbom),
                "vulnerabilities": vulnerabilities(out / f"{name}.vulns.json"),
            }
        )
    run = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ['GITHUB_RUN_ID']}"
        )
    return {
        "version": version,
        "commit": commit,
        "source_date_epoch": epoch,
        "built_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": {"ci": "github-actions" if run else "local", "run": run},
        "tier": config["realm"]["tier"],
        "services": built,
    }


# -------------------------------------------------------------------- files ---
# A files service's artefact (DESIGN.md §15.1): its build's output plus the included paths, as a
# .tar.gz that's the same bytes whenever the same tree is archived at the same commit time.
def archive(tree: Path, dest: Path, epoch: int) -> str:
    """Write `tree` to `dest` deterministically; return its digest, sha256:<hex>.

    Entries in path order, owned by uid and gid 0 with no names, timed at `epoch` (the commit's
    time), mode 0755 for folders and executables and 0644 for the rest; the gzip header has no
    name and no time (gzip -n). Only files and folders: a symlink could point anywhere on the
    host it's unpacked on."""
    entries = []
    for folder, dirs, files in os.walk(tree):
        dirs.sort()
        for name in dirs + sorted(files):
            path = Path(folder) / name
            rel = path.relative_to(tree).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ReleaseError(
                    f"{rel} is a symlink: the archive holds files and folders only; copy what it "
                    "points to instead"
                )
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ReleaseError(f"{rel} is neither a file nor a folder")
            entries.append((rel, path, stat.S_ISDIR(mode), bool(mode & stat.S_IXUSR)))
    entries.sort(key=lambda e: e[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        dest.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for rel, path, is_dir, executable in entries:
            info = tarfile.TarInfo(rel)
            info.mtime = epoch
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if is_dir:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            else:
                info.mode = 0o755 if executable else 0o644
                info.size = path.stat().st_size
                with path.open("rb") as f:
                    tar.addfile(info, f)
    return "sha256:" + sha256(dest)


def files_build(root: Path, service: Service, out: Path, n: str, epoch: int) -> str:
    """Build `service`'s tree from scratch and archive it as out/<name>.<n>.tar.gz; its digest.

    The output folder is removed first, so nothing an earlier build left reaches the archive;
    that's why git mustn't track anything in it. The build runs at the repo's top, with
    SOURCE_DATE_EPOCH set to the commit's time, and its output goes to out/<name>.build-<n>.log.
    Then the output and each included path are copied into a fresh tree, and archived."""
    output = root / service.output
    if not output.resolve().is_relative_to(root.resolve()) or output.resolve() == root.resolve():
        raise ReleaseError(f"{service.name}: output {service.output}/ leads outside the repo")
    tracked = subprocess.run(
        ["git", "ls-files", "--", service.output],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if tracked:
        raise ReleaseError(
            f"{service.name}: git tracks files in {service.output}/; output must be a folder "
            "only the build makes, since it's removed before each build"
        )
    if output.is_symlink() or output.is_file():
        output.unlink()
    elif output.exists():
        shutil.rmtree(output)
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"{service.name}.build-{n}.log"
    with log.open("wb") as f:
        code = subprocess.run(
            ["bash", "-c", service.build],
            cwd=root,
            env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)},
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    if code != 0:
        said = log.read_text(errors="replace").strip().splitlines()[-15:]
        raise ReleaseError(
            f"{service.name}: the build ({service.build}) failed with exit {code}; "
            f"{log.relative_to(root)} ends:\n" + "\n".join(f"     {line}" for line in said)
        )
    if not output.is_dir():
        raise ReleaseError(f"{service.name}: the build made no {service.output}/")
    with tempfile.TemporaryDirectory(prefix="realm-tree-") as tmp:
        tree = Path(tmp) / "tree"
        shutil.copytree(output, tree, symlinks=True)
        for entry in service.include:
            source, _, dest = entry.partition(":")
            src = root / source
            if not src.exists() or not src.resolve().is_relative_to(root.resolve()):
                raise ReleaseError(f"{service.name}: include {entry!r}: no {source} in the repo")
            target = tree / dest
            if target.exists() or target.is_symlink():
                raise ReleaseError(
                    f"{service.name}: include {entry!r}: the build's output already has {dest}; "
                    "an include never overwrites it"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, symlinks=True)
            else:
                shutil.copy2(src, target, follow_symlinks=False)
        return archive(tree, out / f"{service.name}.{n}.tar.gz", epoch)


# ----------------------------------------------------- archives on GitHub ---
# Decision 1 of DESIGN.md §15.9: a files release's archives are assets of the GitHub release on
# its tag (a draft until the release workflow fills it in). The repo is private, so are they.
def github_repo_from(url: str) -> str:
    """owner/name from a github.com remote URL ('' for any other host)."""
    m = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([\w.-]+/[\w.-]+?)(?:\.git)?/?",
        url.strip(),
    )
    return m.group(1) if m else ""


def github_repo(root: Path) -> str:
    """The GitHub repo releases belong to: $GITHUB_REPOSITORY in CI, else origin's."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    repo = github_repo_from(url)
    if not repo:
        raise ReleaseError(
            "no GitHub repo to keep the archives in: set GITHUB_REPOSITORY=owner/name, or an "
            "origin remote on github.com"
        )
    return repo


def gh(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=not binary, check=False)


def gh_api(path: str, *args: str) -> Any:
    done = gh("api", path, *args)
    if done.returncode != 0:
        raise ReleaseError(f"gh api {path}: {done.stderr.strip() or 'failed'}")
    return json.loads(done.stdout)


def gh_pages(path: str) -> list:
    """Every item of a paged GitHub list (100 a page)."""
    items, page = [], 1
    while True:
        batch = gh_api(f"{path}?per_page=100&page={page}")
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def tag_on_github(repo: str, version: str) -> None:
    done = gh("api", f"repos/{repo}/git/ref/tags/{version}")
    if done.returncode == 0:
        return
    if "HTTP 404" in done.stderr:
        raise ReleaseError(
            f"the tag {version} isn't on GitHub ({repo}): push it first; the release's "
            "archives are kept on it"
        )
    raise ReleaseError(f"couldn't ask GitHub for the tag {version}: {done.stderr.strip()}")


def github_release_id(repo: str, version: str) -> int:
    """The id of the GitHub release on `version`'s tag, drafts included (0 if there's none)."""
    for r in gh_pages(f"repos/{repo}/releases"):
        if r.get("tag_name") == version:
            return int(r["id"])
    return 0


def github_release(repo: str, version: str) -> int:
    """The id of the GitHub release on `version`'s tag, drafts included; made as a draft if none."""
    found = github_release_id(repo, version)
    if found:
        return found
    made = gh_api(
        f"repos/{repo}/releases",
        "-X",
        "POST",
        "-f",
        f"tag_name={version}",
        "-f",
        f"name={version}",
        "-F",
        "draft=true",
        "-f",
        "body=Release in progress: the pipeline fills this in after staging.",
    )
    return int(made["id"])


def download_asset(repo: str, asset_id: int) -> bytes:
    done = gh(
        "api",
        "-H",
        "Accept: application/octet-stream",
        f"repos/{repo}/releases/assets/{asset_id}",
        binary=True,
    )
    if done.returncode != 0:
        raise ReleaseError(f"couldn't download asset {asset_id}: {done.stderr.decode().strip()}")
    return done.stdout


def asset_digest(repo: str, asset_id: int) -> str:
    return "sha256:" + hashlib.sha256(download_asset(repo, asset_id)).hexdigest()


def publish_files(root: Path, declared: list[Service], version: str) -> None:
    """Keep each files service's archive and its signature on the tag's GitHub release. An
    archive already there with the same digest is left as it is; a different one is refused."""
    out = root / "dist" / version
    repo = github_repo(root)
    tag_on_github(repo, version)
    release_id = github_release(repo, version)
    for s in (s for s in declared if s.kind == "files"):
        archived, bundle = out / f"{s.name}.tar.gz", out / f"{s.name}.tar.gz.bundle"
        for path in (archived, bundle):
            if not path.exists():
                raise ReleaseError(f"no {path.relative_to(root)}: build {version} first")
        digest = "sha256:" + sha256(archived)
        print(f"\n-> {s.name} -> {repo}, release {version}: {archived.name}")
        assets = {
            a["name"]: int(a["id"]) for a in gh_pages(f"repos/{repo}/releases/{release_id}/assets")
        }
        if archived.name in assets:
            held = asset_digest(repo, assets[archived.name])
            if held != digest:
                raise ReleaseError(
                    f"{version}'s GitHub release already holds a different {archived.name} "
                    f"({held}, not the built {digest}); a release's archive is never replaced"
                )
            missing = [] if bundle.name in assets else [str(bundle)]
            print(f"   already archived with its digest: {digest}")
        else:
            missing = [str(archived), str(bundle)]
        if missing:
            done = gh("release", "upload", version, "--repo", repo, *missing)
            if done.returncode != 0:
                raise ReleaseError(
                    f"{s.name}: couldn't upload to {version}'s release: {done.stderr.strip()}"
                )
        if archived.name not in assets:
            assets = {
                a["name"]: int(a["id"])
                for a in gh_pages(f"repos/{repo}/releases/{release_id}/assets")
            }
            held = asset_digest(repo, assets[archived.name]) if archived.name in assets else ""
            if held != digest:
                raise ReleaseError(
                    f"{s.name}: the release holds {held or 'nothing'}, not the built {digest}"
                )
            print(f"   archived with its digest: {digest}")


# ------------------------------------------------------------------ records ---
# docs/releases/<version>.md (DESIGN.md §7.7). The pipeline writes it; people fill in the UAT
# sign-off and the exploratory-testing notes; promote reads it back.
STATES = ("staged", "rejected", "live", "replaced", "rolled back")
PLACEHOLDER = re.compile(r"<[^>]+>")


def records_dir(root: Path) -> Path:
    return root / "docs" / "releases"


def record_path(root: Path, version: str) -> Path:
    return records_dir(root) / f"{version}.md"


def field(text: str, name: str) -> str:
    m = re.search(rf"^- {re.escape(name)}:[ \t]*(.*?)\s*$", text, flags=re.M)
    return m.group(1).strip() if m else ""


def set_field(text: str, name: str, value: str) -> str:
    pattern = rf"^(- {re.escape(name)}:)[ \t]*.*$"
    if not re.search(pattern, text, flags=re.M):
        raise ReleaseError(f"the release record has no '- {name}:' line")
    return re.sub(pattern, lambda m: f"{m.group(1)} {value}", text, count=1, flags=re.M)


def section_text(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip() if m else ""


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version[1:].split("."))


def records(root: Path) -> dict[str, str]:
    folder = records_dir(root)
    found = (
        {
            p.stem: p.read_text(encoding="utf-8")
            for p in folder.glob("v*.md")
            if VERSION.fullmatch(p.stem)
        }
        if folder.is_dir()
        else {}
    )
    return dict(sorted(found.items(), key=lambda kv: version_key(kv[0])))


def live_version(root: Path, other_than: str = "") -> str:
    """The release production runs now, as the records say ('' if none yet)."""
    live = [
        v for v, text in records(root).items() if field(text, "State") == "live" and v != other_than
    ]
    if len(live) > 1:
        raise ReleaseError(f"more than one release record says it's live: {', '.join(live)}")
    return live[0] if live else ""


def uat_problems(text: str) -> list[str]:
    problems = []
    uat = section_text(text, "UAT sign-off")
    for name in ("Signed off by", "Date", "Tested"):
        value = field(uat, name)
        if not value or PLACEHOLDER.search(value):
            problems.append(f"UAT sign-off: '{name}' isn't filled in")
    signed = field(uat, "Date")
    if signed and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", signed):
        problems.append("UAT sign-off: Date is YYYY-MM-DD")
    if not section_text(text, "Exploratory testing"):
        problems.append("Exploratory testing: no notes yet (what was tried, and what was found)")
    return problems


def freeze_window(config: dict, today: dt.date) -> str:
    """The freeze window `today` falls in, from realm.toml [release] freeze, or ''."""
    for window in config.get("release", {}).get("freeze", []):
        start, sep, end = str(window).partition("/")
        try:
            first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            raise ReleaseError(
                f"[release] freeze entry {window!r}: write it as YYYY-MM-DD/YYYY-MM-DD"
            ) from None
        if not sep or last < first:
            raise ReleaseError(f"[release] freeze entry {window!r}: start/end, in order")
        if first <= today <= last:
            return str(window)
    return ""


def promotable(
    root: Path, config: dict, version: str, today: dt.date, emergency: str = ""
) -> list[str]:
    """Why `version` can't be promoted now (empty: it can)."""
    path = record_path(root, version)
    if not path.exists():
        return [f"no release record {path.relative_to(root)}: stage {version} first"]
    text = path.read_text(encoding="utf-8")
    problems = []
    state = field(text, "State")
    if state != "staged":
        problems.append(f"{version} is {state or 'in no state'}, not staged")
    problems += uat_problems(text)
    window = freeze_window(config, today)
    if window and not emergency:
        problems.append(
            f"today is in the release freeze {window}: promote with --emergency "
            '"<reason>" only for a fix that can\'t wait'
        )
    return problems


def shipped(
    root: Path, since: str, commit: str, tasks: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    """The tasks named by the commits in since..commit, and the requirements those tasks serve."""
    rng = f"{since}..{commit}" if since else commit
    out = subprocess.run(
        ["git", "log", "--format=%s", rng], cwd=root, capture_output=True, text=True, check=False
    ).stdout
    named = sorted(set(re.findall(r"\bT\d{3,}\b", out)), key=lambda t: int(t[1:]))
    reqs = sorted({r for task in named for r in tasks.get(task, [])})
    return named, reqs


def render(
    version: str,
    commit: str,
    config: dict,
    previous: str,
    tasks: list[str],
    reqs: list[str],
    build: dict,
    checks: list[list[str]],
    state: str,
) -> str:
    """A new release record, as release.sh stage writes it."""
    deploy = config.get("deploy", {})
    platform = deploy.get("platform", "?")
    mode = f" ({deploy.get('mode', 'source')})" if platform == "railway" else ""
    images = "\n".join(
        f"| {s['name']} | {s['image']} | {s['digest']} | {'yes' if s['reproducible'] else 'no'} "
        f"| {s['sbom']} (sha256 {s['sbom_sha256'][:12]}) | {s['vulnerabilities']} |"
        for s in build.get("services", [])
    )
    rows = "\n".join(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} |" for c in checks)
    builder = build.get("builder") or {}
    # Where it was built: a release run from a developer's machine (a host that firewalls
    # GitHub's runners, DESIGN.md §15.4) says so in its record.
    built_by = (
        ""
        if not builder
        else f"- Built by: GitHub Actions, {builder.get('run')}\n"
        if builder.get("ci") == "github-actions"
        else "- Built by: this machine, not CI (DESIGN.md §15.4)\n"
    )
    return f"""# Release {version}

- State: {state}
- Commit: {commit}
- Tier: {config["realm"]["tier"]} · Platform: {platform}{mode}
{built_by}- Previous: {previous or "none (the first release)"}
- Requirements: {", ".join(reqs) or "none"}
- Tasks: {", ".join(tasks) or "none"}

## Images

| Service | Image | Digest | Reproducible | SBOM | Known vulnerabilities |
|---|---|---|---|---|---|
{images}

The provenance, `release.json`, is signed with the project key (`cosign.pub`) in
`release.bundle`. The release workflow attaches both to the GitHub release, with the SBOMs and the
traceability matrix.

## Release checks (staging)

| Check | Target | Result | Detail |
|---|---|---|---|
{rows}

## UAT sign-off

<!-- Whoever ran user acceptance testing on staging fills this in. promote refuses without it. -->
- Signed off by:
- Date:
- Tested:

## Exploratory testing

<!-- What was tried beyond the scripted tests, and what was found. promote refuses it empty. -->

## Promotion

Not promoted yet: `bash scripts/realm/release.sh promote {version}` after the UAT sign-off.

## Rollback

To put this version back in production later: `bash scripts/realm/release.sh rollback {version}`
"""


def replace_section(text: str, heading: str, body: str) -> str:
    pattern = rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^## |\Z)"
    if not re.search(pattern, text, flags=re.S | re.M):
        raise ReleaseError(f"the release record has no '## {heading}' section")
    return re.sub(
        pattern,
        lambda m: m.group(1) + "\n" + body.strip() + "\n\n",
        text,
        count=1,
        flags=re.S | re.M,
    )


# ---------------------------------------------------------- service levels ---
def load_slos(root: Path, names: list[str], workers: list[str] | None = None) -> dict:
    """docs/ops/slo.toml, checked: every web service in `names` has objectives, no worker has."""
    path = root / "docs" / "ops" / "slo.toml"
    if not path.exists():
        raise ReleaseError(
            "no docs/ops/slo.toml: every deployed service needs its service "
            "level objectives before it's released"
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    slos = data.get("slo", [])
    for n, s in enumerate(slos, 1):
        if s.get("service") in (workers or []):
            raise ReleaseError(
                f"slo.toml [[slo]] {n}: {s.get('service')} is a worker; workers have no URL to "
                "watch; set the objective on the web service in front of it"
            )
        if s.get("service") not in names:
            raise ReleaseError(
                f"slo.toml [[slo]] {n}: service {s.get('service')!r} isn't a "
                "[[service]] in realm.toml"
            )
        if not str(s.get("path", "")).startswith("/"):
            raise ReleaseError(f"slo.toml [[slo]] {n}: path must be what's measured, like /health")
        if "objective_percent" not in s and "p95_ms" not in s:
            raise ReleaseError(f"slo.toml [[slo]] {n}: give objective_percent or p95_ms")
    missing = [n for n in names if n not in {s.get("service") for s in slos}]
    if missing:
        raise ReleaseError(f"slo.toml has no [[slo]] for: {', '.join(missing)}")
    return data


def watch_script(slos: dict, urls: dict[str, str]) -> str:
    """A k6 script for the watch window: steady traffic, with the SLOs as thresholds."""
    watch = slos.get("watch", {})
    minutes = float(watch.get("minutes", 10))
    rate = int(watch.get("rate", 5))
    thresholds, calls = {}, []
    for n, s in enumerate(slos["slo"]):
        tag = f"slo{n}"
        target = urls[s["service"]].rstrip("/") + s["path"]
        calls.append(f"  http.get({json.dumps(target)}, {{ tags: {{ slo: '{tag}' }} }});")
        if "objective_percent" in s:
            budget = round(1 - float(s["objective_percent"]) / 100, 6)
            thresholds[f"http_req_failed{{slo:{tag}}}"] = [f"rate<={budget}"]
        if "p95_ms" in s:
            thresholds[f"http_req_duration{{slo:{tag}}}"] = [f"p(95)<{float(s['p95_ms'])}"]
    duration = f"{int(minutes * 60)}s"
    return f"""// The watch window: `realm release watch-script` writes it from docs/ops/slo.toml.
import http from 'k6/http';

export const options = {{
  scenarios: {{
    watch: {{ executor: 'constant-arrival-rate', rate: {rate}, timeUnit: '1s',
             duration: '{duration}', preAllocatedVUs: {max(2, rate * 2)} }},
  }},
  thresholds: {json.dumps(thresholds, indent=2)},
}};

export default function () {{
{chr(10).join(calls)}
}}
"""


# ---------------------------------------------------------------- incidents ---
def next_incident(root: Path) -> str:
    folder = root / "docs" / "ops" / "incidents"
    numbers = (
        [
            int(m.group(1))
            for p in folder.glob("INC-*.md")
            if (m := re.fullmatch(r"INC-(\d{4})", p.stem))
        ]
        if folder.is_dir()
        else []
    )
    return f"INC-{max(numbers, default=0) + 1:04d}"


def incident(number: str, version: str, restored: str, detail: str, when: str) -> str:
    return f"""# {number} — {version} broke its service level objectives in the watch window

- Status: open
- Opened: {when} · Release: {version} · Rolled back to: {restored or "nothing (no earlier release)"}
- Detected by: the release's watch window (k6 against docs/ops/slo.toml)

## What happened

{detail.strip() or "The watch window failed; see the release workflow run."}

## Timeline

- {when}: {version} promoted to production, then watched
- {when}: an objective broke; {restored or "no earlier release"} redeployed by the pipeline

## Postmortem

<!-- Blameless: what in the system let this reach production, and why nothing caught it sooner.
     Ask what, not who. -->

## The change that stops it recurring

<!-- Required before this incident can close: the commit or PR that changes a file so it can't
     happen again (a test, a check, a limit, an alert). A resolution to "be careful" isn't one. -->
"""


# --------------------------------------------------------------------- refs ---
def load_build(root: Path, version: str) -> dict:
    path = root / "dist" / version / "release.json"
    if not path.exists():
        raise ReleaseError(f"no {path.relative_to(root)}: build {version} first")
    return json.loads(path.read_text(encoding="utf-8"))


def image_digests(text: str) -> dict[str, str]:
    """Service -> digest, from a release record's Images table."""
    found = {}
    for line in section_text(text, "Images").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2].startswith("sha256:"):
            found[cells[0]] = cells[2]
    return found


def ref(root: Path, config: dict, version: str, service: str) -> str:
    """What the platform deploys for `service` at `version`: an image, or a commit to build."""
    deploy = config.get("deploy", {})
    platform, mode = deploy.get("platform"), deploy.get("mode", "source")
    path = record_path(root, version)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if platform == "compose":
        return f"realm-{config['realm']['name']}-{service}:{version}"
    if platform == "cpanel":  # the archive, by the release it belongs to and its digest (§15.3)
        digests = (
            image_digests(text)
            if text
            else {s["name"]: s["digest"] for s in load_build(root, version)["services"]}
        )
        if service not in digests:
            raise ReleaseError(f"{version} has no archive for {service} on record")
        return f"{version}/{service}.tar.gz@{digests[service]}"
    if platform == "railway" and mode == "source":
        commit = field(text, "Commit") if text else load_build(root, version)["commit"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ReleaseError(f"{version} has no commit on record")
        return commit
    if platform == "aws" or (platform == "railway" and mode == "image"):
        registry = str(deploy.get("registry", "")).rstrip("/")
        if not registry:
            raise ReleaseError(
                f"{'aws' if platform == 'aws' else 'railway image mode'} needs [deploy] "
                "registry (e.g. ghcr.io/owner/repo)"
            )
        digests = (
            image_digests(text)
            if text
            else {s["name"]: s["digest"] for s in load_build(root, version)["services"]}
        )
        if service not in digests:
            raise ReleaseError(f"{version} has no image for {service} on record")
        return f"{registry}/{service}@{digests[service]}"
    raise ReleaseError(
        f"[deploy] platform {platform!r} / mode {mode!r}: use compose, aws, cpanel, or railway "
        "with source or image"
    )


# ------------------------------------------------------------ deploy checks ---
# Which environments' URLs a command needs: all of them by default, one for a command that
# deploys to one, none for publish (DESIGN.md §14.3's order: the seed is archived, the
# infrastructure is created from it, staging runs it, and production is made from what staging
# proved — so each URL exists only once that environment does).
ENVIRONMENTS = ("staging", "production")


def deploy_problems(config: dict, urls: tuple[str, ...] = ENVIRONMENTS) -> list[str]:
    """Settings the platform needs before anything is deployed (DESIGN.md §5.2). `urls` is the
    environments whose web-service URLs must be set: publish passes none, because it archives
    the seed before anything serves it, and stage passes staging, because production is created
    later, from the release it stages."""
    deploy = config.get("deploy", {})
    platform, mode = deploy.get("platform"), deploy.get("mode", "source")
    if platform == "cpanel":
        return cpanel_problems(config, urls)
    files = [
        f'service {s.get("name")} is kind = "files": only the cpanel platform deploys a file '
        "tree (DESIGN.md §15)"
        for s in config.get("service", [])
        if s.get("kind") == "files"
    ]
    if platform == "compose":
        return files + compose_problems(config)
    if platform == "aws":
        return files + aws_problems(config, urls)
    if platform != "railway":
        return [f"[deploy] platform is {platform!r}: use railway, aws, cpanel or compose"]
    problems = files
    if mode not in ("source", "image"):
        problems.append(f"[deploy] mode is {mode!r}: use source or image")
    if config["realm"]["tier"] == "assured" and mode != "image":
        problems.append(
            "the assured tier deploys the signed image itself: set [deploy] mode = "
            '"image" (Railway Pro, for a private registry)'
        )
    if mode == "image" and not deploy.get("registry"):
        problems.append("image mode needs [deploy] registry, e.g. ghcr.io/<owner>/<repo>")
    for env in ("staging", "production"):
        if not deploy.get(env):
            problems.append(f"[deploy] {env} needs the Railway environment's ID")
    for s in config.get("service", []):
        if not s.get("railway_service"):
            problems.append(f"[[service]] {s.get('name')} needs railway_service (its Railway ID)")
        if s.get("kind") == "worker":
            continue  # no URL: the adapter's health verb checks it
        for env in urls:
            if not str(s.get(f"{env}_url", "")).startswith("https://"):
                problems.append(f"[[service]] {s.get('name')} needs {env}_url (https://…)")
    return problems


# The compose platform publishes each environment's services on 127.0.0.1, one port a service,
# counting up from a base. A second project on the same Docker host moves its bases.
COMPOSE_PORTS = {"staging": 18000, "production": 19000}


def compose_port(config: dict, env: str) -> int:
    """The first local port the compose platform publishes `env` on: [deploy] staging_port or
    production_port, else 18000 or 19000. Each [[service]] takes the next one, by its place in
    the list."""
    key = f"{env}_port"
    port = config.get("deploy", {}).get(key, COMPOSE_PORTS[env])
    last = 65536 - max(len(config.get("service", [])), 1)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= last:
        raise ReleaseError(
            f"[deploy] {key} must be a port number from 1024 to {last}, leaving one port for "
            f"each [[service]]: {port!r}"
        )
    return port


def compose_problems(config: dict) -> list[str]:
    """The compose platform's settings: a usable base port for each environment, and two
    ranges that don't share a port."""
    problems, bases = [], []
    for env in ENVIRONMENTS:
        try:
            bases.append(compose_port(config, env))
        except ReleaseError as e:
            problems.append(str(e))
    count = max(len(config.get("service", [])), 1)
    if len(bases) == 2 and abs(bases[0] - bases[1]) < count:
        problems.append(
            f"[deploy] staging_port and production_port overlap: each environment takes "
            f"{count} port(s) from its own, one for each [[service]]"
        )
    return problems


def ecr_registry(registry: str, region: str = r"[a-z0-9-]+") -> bool:
    """Whether `registry` is a repository path in an ECR registry (in `region`, if given)."""
    return bool(
        re.fullmatch(rf"\d{{12}}\.dkr\.ecr\.{region}\.amazonaws\.com/[a-z0-9._/-]+", registry)
    )


def aws_problems(config: dict, urls: tuple[str, ...] = ENVIRONMENTS) -> list[str]:
    """The aws platform's settings (DESIGN.md §14.3): the region, the ECR registry that
    aws-bootstrap.sh fills in, each service's runtime, and a web service's URL in each of the
    `urls` environments."""
    deploy = config.get("deploy", {})
    region = str(deploy.get("region", ""))
    problems = []
    if not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", region):
        problems.append("[deploy] region needs the AWS region, e.g. eu-west-1")
    registry = str(deploy.get("registry", "")).rstrip("/")
    if not ecr_registry(registry, re.escape(region) if region else r"[a-z0-9-]+"):
        problems.append(
            f"[deploy] registry needs the project's ECR repository in {region or 'the region'}, "
            "<account>.dkr.ecr.<region>.amazonaws.com/<name> (aws-bootstrap.sh writes it)"
        )
    for s in config.get("service", []):
        if s.get("runtime") not in ("ecs", "lambda"):
            problems.append(f'[[service]] {s.get("name")} needs runtime = "ecs" or "lambda"')
        if s.get("kind") == "worker":
            continue  # no URL: the adapter's health verb checks it
        for env in urls:
            if not str(s.get(f"{env}_url", "")).startswith("https://"):
                problems.append(f"[[service]] {s.get('name')} needs {env}_url (https://…)")
    return problems


def cpanel_problems(config: dict, urls: tuple[str, ...] = ENVIRONMENTS) -> list[str]:
    """The cpanel platform's settings (DESIGN.md §15.2): the SSH host, where the archives are
    kept, every service a files service with its two document roots, and each one's URL in each
    of the `urls` environments."""
    deploy = config.get("deploy", {})
    problems = []
    if not str(deploy.get("ssh_host", "")).strip():
        problems.append(
            "[deploy] ssh_host needs the Host in ~/.ssh/config that reaches the server (the "
            "release workflows write the same entry)"
        )
    if deploy.get("archive") != "github-release":
        problems.append(
            '[deploy] archive = "github-release": the release archives are kept on the '
            "tag's GitHub release (DESIGN.md §15.9)"
        )
    for s in config.get("service", []):
        if s.get("kind") != "files":
            problems.append(
                f'service {s.get("name")}: the cpanel platform deploys kind = "files" services '
                "only; it runs no containers"
            )
            continue
        for env in urls:
            if not str(s.get(f"{env}_url", "")).startswith("https://"):
                problems.append(f"[[service]] {s.get('name')} needs {env}_url (https://…)")
    return problems + root_problems(config)


def root_problems(config: dict) -> list[str]:
    """Each files service's staging_root and production_root: absolute, written plainly, deep
    enough, and never the same as or inside another root. The adapter's rsync --delete empties
    whatever the root holds that the release doesn't, so a root inside another would be wiped by
    the outer one's deploy (DESIGN.md §15.3)."""
    problems, roots = [], []
    for s in config.get("service", []):
        if s.get("kind") != "files":
            continue
        name = s.get("name")
        for env in ENVIRONMENTS:
            key = f"{env}_root"
            value = str(s.get(key, ""))
            if not value:
                problems.append(
                    f"{name} needs {key}, the document root's absolute path on the host"
                )
            elif not value.startswith("/") or posixpath.normpath(value) != value:
                problems.append(
                    f"{name}: {key} must be an absolute path, written plainly (no .., no "
                    f"trailing /): {value!r}"
                )
            elif len(PurePosixPath(value).parts) < 4:
                problems.append(
                    f"{name}: {key} {value} is too near the top: a deploy empties the root of "
                    "everything the release doesn't have"
                )
            else:
                roots.append((name, key, env, PurePosixPath(value)))
    for i, (n1, k1, e1, r1) in enumerate(roots):
        for n2, k2, e2, r2 in roots[i + 1 :]:
            same = n1 == n2
            if r1 == r2:
                problems.append(
                    f"{n1}: {k1} and {k2} are the same folder"
                    if same
                    else f"{n1}'s {k1} and {n2}'s {k2} are the same folder"
                )
                continue
            for (na, ka), (nb, kb, eb), inner, outer in (
                ((n1, k1), (n2, k2, e2), r1, r2),
                ((n2, k2), (n1, k1, e1), r2, r1),
            ):
                if inner.is_relative_to(outer):
                    problems.append(
                        f"{na}: {ka} is inside {kb}: {eb}'s --delete would remove it"
                        if same
                        else f"{na}'s {ka} is inside {nb}'s {kb}: {nb}'s deploy to {eb} would "
                        "remove it"
                    )
    return problems


# The ZAP baseline scan: a warning blocks the release unless the project has decided about that
# rule, with a reason, in docs/release/zap-rules.tsv (id, action, name, reason).
ZAP_ACTIONS = ("IGNORE", "WARN", "FAIL", "INFO")


def zap_rules(root: Path) -> str:
    """ZAP's config file (id, action, name) from the project's reasoned list; '' if none."""
    path = root / "docs" / "release" / "zap-rules.tsv"
    if not path.exists():
        return ""
    lines = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        cells = [c.strip() for c in raw.split("\t")]
        if len(cells) < 4 or not cells[0].isdigit() or cells[1] not in ZAP_ACTIONS:
            raise ReleaseError(
                f"docs/release/zap-rules.tsv:{n}: rule id, action "
                f"({'/'.join(ZAP_ACTIONS)}), name, reason, separated by tabs"
            )
        if cells[1] == "IGNORE" and len(cells[3]) < 10:
            raise ReleaseError(
                f"docs/release/zap-rules.tsv:{n}: say why rule {cells[0]} is ignored"
            )
        lines.append(f"{cells[0]}\t{cells[1]}\t({cells[2]})")
    return "\n".join(lines) + "\n"


def zap_detail(log: str, code: int) -> str:
    """A failed baseline scan, as one cell of the release record: each rule ZAP failed or
    warned on, then its totals. A run that printed neither is named by its exit code.

    It's one line with no tab or bar, because it becomes a row of checks.tsv and of the
    record's table: several failed rules used to break both."""
    found = [
        " ".join(line.replace("|", "/").split())
        for line in log.splitlines()
        if line.startswith(("FAIL-NEW:", "WARN-NEW:"))
    ]
    text = "; ".join(found) or f"zap exited {code}"
    return text if len(text) <= 400 else text[:399] + "…"


# ------------------------------------------------------- performance secrets ---
def perf_env(text: str) -> list[tuple[str, str]]:
    """The secret PERF_ENV's KEY=value lines (blank and # lines skipped), for the k6 scripts.

    It holds credentials, such as a test user's password, so no error message quotes a line."""
    pairs = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep:
            raise ReleaseError(f"PERF_ENV line {n} isn't KEY=value (the line isn't shown)")
        if not ENV_KEY.fullmatch(key):
            raise ReleaseError(
                f"PERF_ENV line {n}: the name must be capitals, digits and _, like "
                "TEST_USER_PASSWORD (the line isn't shown)"
            )
        pairs.append((key, value))
    return pairs


# ---------------------------------------------------------------------- cli ---
def now() -> dt.datetime:
    fake = os.environ.get("REALM_NOW")  # tests and rehearsals
    return dt.datetime.fromisoformat(fake) if fake else dt.datetime.now(dt.UTC)


def stamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M UTC")


def cli(root: Path, config: dict, args: list[str], tasks: dict[str, list[str]], git) -> int:
    parser = argparse.ArgumentParser(prog="realm release")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("services")
    sub.add_parser("names")
    c = sub.add_parser("config")
    c.add_argument("key")
    dc = sub.add_parser("deploy-check")
    dc.add_argument(
        "--urls",
        default="all",
        choices=("all", "none", *ENVIRONMENTS),
        help="whose web-service URLs must be set: all (the default), one environment's, or none",
    )
    sub.add_parser("perf-env")
    fb = sub.add_parser("files-build")
    fb.add_argument("version")
    fb.add_argument("service")
    fb.add_argument("n", choices=("1", "2"), help="which of the two builds")
    pf = sub.add_parser("publish-files")
    pf.add_argument("version")
    z = sub.add_parser("zap-rules")
    z.add_argument("out")
    zd = sub.add_parser("zap-detail")
    zd.add_argument("log")
    zd.add_argument("code", type=int)
    cp = sub.add_parser("compose-port")
    cp.add_argument("env", choices=ENVIRONMENTS)
    for name in ("provenance", "previous", "promotable", "slo-check"):
        p = sub.add_parser(name)
        if name != "slo-check":
            p.add_argument("version")
        if name == "promotable":
            p.add_argument("--emergency", default="")
    r = sub.add_parser("ref")
    r.add_argument("version")
    r.add_argument("service")
    rs = sub.add_parser("record-staged")
    rs.add_argument("version")
    rs.add_argument("checks", help="the stage's results: check, target, result, detail (TSV)")
    rp = sub.add_parser("record-promoted")
    rp.add_argument("version")
    rp.add_argument("--watch", required=True)
    rp.add_argument("--emergency", default="")
    rr = sub.add_parser("record-rolled-back")
    rr.add_argument("version")
    rr.add_argument("--to", default="")
    rr.add_argument("--reason", required=True)
    rb = sub.add_parser("record-rollback")
    rb.add_argument("version", help="the release now back in production")
    w = sub.add_parser("watch-script")
    w.add_argument("urls", nargs="+", help="service=url for each service in production")
    i = sub.add_parser("incident")
    i.add_argument("version")
    i.add_argument("--to", default="")
    i.add_argument("--detail-file", required=True)
    a = parser.parse_args(args)

    unchecked = ("config", "perf-env", "names", "zap-detail")  # these read no [[service]]
    declared = services(config, root) if a.command not in unchecked else []
    names = [s.name for s in declared if s.kind != "worker"]  # every service with a URL
    workers = [s.name for s in declared if s.kind == "worker"]
    if a.command == "services":
        print("\n".join(s.row() for s in services(config, root)))
    elif a.command == "config":
        print(config_value(config, a.key))
    elif a.command == "names":
        for s in config.get("service", []):
            if not NAME.fullmatch(str(s.get("name", ""))):
                raise ReleaseError(
                    f"[[service]] {s.get('name')!r}: lowercase letters, digits and -"
                )
            print(s["name"])
    elif a.command == "provenance":
        version = check_version(a.version)
        out = root / "dist" / version
        commit = git(root, "rev-parse", "HEAD").stdout.strip()
        epoch = int(git(root, "log", "-1", "--format=%ct", "HEAD").stdout.strip())
        data = provenance(version, out, commit, epoch, config)
        (out / "release.json").write_text(json.dumps(data, indent=2) + "\n")
        print(f"   wrote {(out / 'release.json').relative_to(root)}")
    elif a.command == "files-build":
        version = check_version(a.version)
        service = next((s for s in declared if s.name == a.service and s.kind == "files"), None)
        if service is None:
            raise ReleaseError(f"no files service called {a.service!r} in realm.toml")
        epoch = int(git(root, "log", "-1", "--format=%ct", "HEAD").stdout.strip())
        print(files_build(root, service, root / "dist" / version, a.n, epoch))
    elif a.command == "publish-files":
        publish_files(root, declared, check_version(a.version))
    elif a.command == "deploy-check":
        wanted = {"all": ENVIRONMENTS, "none": ()}.get(a.urls, (a.urls,))
        problems = deploy_problems(config, urls=wanted)
        for problem in problems:
            print(f"!! {problem}")
        return 1 if problems else 0
    elif a.command == "zap-rules":
        rules = zap_rules(root)
        Path(a.out).write_text(rules)
        print("   zap rules: " + (f"{len(rules.splitlines())} decided" if rules else "none"))
    elif a.command == "zap-detail":
        log = Path(a.log)
        print(zap_detail(log.read_text(errors="replace") if log.exists() else "", a.code))
    elif a.command == "compose-port":
        problems = compose_problems(config)
        if problems:
            raise ReleaseError("; ".join(problems))
        print(compose_port(config, a.env))
    elif a.command == "previous":
        print(live_version(root, other_than=check_version(a.version)))
    elif a.command == "ref":
        print(ref(root, config, check_version(a.version), a.service))
    elif a.command == "slo-check":
        load_slos(root, names, workers)
        print("   slo.toml: every web service has its objectives")
    elif a.command == "perf-env":
        # Checked in full before anything is printed; release.sh exports each pair for k6.
        for key, value in perf_env(os.environ.get("PERF_ENV", "")):
            print(f"{key}={value}")
    elif a.command == "promotable":
        problems = promotable(root, config, check_version(a.version), now().date(), a.emergency)
        for problem in problems:
            print(f"!! {problem}")
        return 1 if problems else 0
    elif a.command == "record-staged":
        version = check_version(a.version)
        build = load_build(root, version)
        previous = live_version(root, other_than=version)
        since = (
            field(records(root).get(previous, ""), "Commit")
            if previous
            else str(config.get("trace", {}).get("since", ""))
        )
        named, reqs = shipped(root, since, build["commit"], tasks)
        checks = [line.split("\t") for line in Path(a.checks).read_text().splitlines() if line]
        ok = all(c[2] in ("pass", "not applicable") for c in checks)
        text = render(
            version,
            build["commit"],
            config,
            previous,
            named,
            reqs,
            build,
            checks,
            "staged" if ok else "rejected",
        )
        path = record_path(root, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"   wrote {path.relative_to(root)}: {'staged' if ok else 'rejected'}")
        return 0 if ok else 1
    elif a.command == "record-promoted":
        version = check_version(a.version)
        replaced = live_version(root, other_than=version)
        path = record_path(root, version)
        text = set_field(path.read_text(encoding="utf-8"), "State", "live")
        note = f"- Promoted: {stamp()}\n- Watch window: {a.watch}"
        if a.emergency:
            note += f"\n- Emergency promotion during a release freeze: {a.emergency}"
        path.write_text(replace_section(text, "Promotion", note), encoding="utf-8")
        if replaced:
            old = record_path(root, replaced)
            old.write_text(
                set_field(old.read_text(encoding="utf-8"), "State", "replaced"), encoding="utf-8"
            )
        print(f"   {version} is live" + (f"; {replaced} replaced" if replaced else ""))
    elif a.command == "record-rolled-back":
        version = check_version(a.version)
        path = record_path(root, version)
        text = set_field(path.read_text(encoding="utf-8"), "State", "rolled back")
        note = (
            f"- Promoted, then rolled back: {stamp()}\n- Why: {a.reason}\n"
            f"- Production runs: {a.to or 'nothing earlier (it was the first release)'}"
        )
        path.write_text(replace_section(text, "Promotion", note), encoding="utf-8")
        print(f"   {version} rolled back")
    elif a.command == "record-rollback":
        version = check_version(a.version)
        current = live_version(root, other_than=version)
        if current:
            old = record_path(root, current)
            text = set_field(old.read_text(encoding="utf-8"), "State", "rolled back")
            old.write_text(text, encoding="utf-8")
        path = record_path(root, version)
        text = set_field(path.read_text(encoding="utf-8"), "State", "live")
        text = replace_section(
            text,
            "Promotion",
            section_text(text, "Promotion") + f"\n- Back in production by rollback: {stamp()}",
        )
        path.write_text(text, encoding="utf-8")
        print(f"   {version} is live again" + (f"; {current} rolled back" if current else ""))
    elif a.command == "watch-script":
        urls = dict(u.split("=", 1) for u in a.urls)
        print(watch_script(load_slos(root, names, workers), urls))
    elif a.command == "incident":
        number = next_incident(root)
        detail = Path(a.detail_file).read_text() if Path(a.detail_file).exists() else ""
        folder = root / "docs" / "ops" / "incidents"
        folder.mkdir(parents=True, exist_ok=True)
        text = incident(number, check_version(a.version), a.to, detail, stamp())
        (folder / f"{number}.md").write_text(text, encoding="utf-8")
        print(number)
    return 0
