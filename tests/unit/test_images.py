"""What each function's image carries, as opposed to what the repository does.

Code run from the repository can reach anything beside it. The same code in an image finds only
what its Dockerfile copied in, and only what .dockerignore let through to the build. So a file
the code reads at run time can be present in every test and absent from every image, and
nothing fails until staging.

That happened to the curated law. `sources.root()` looks for the sections beside the package
(`<task root>/legal/sections`) and then in the repository's `docs/`. No image copied them, so
inside the `ocr` image there were none. The rule catalogue refuses a rule that cites a section
it can't find (REQ-006), so every lease failed at its analysis.

These tests rebuild each image's file layout from those two files, without Docker, and run the
code that needs the law against it.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from tokelo.core import sources

ROOT = Path(__file__).resolve().parents[2]

# Where Lambda's own Python base images put the function (the ocr image sets its own WORKDIR).
LAMBDA_TASK_ROOT = "/var/task"


def ignore_rules() -> list[tuple[str, bool]]:
    """.dockerignore's patterns, in order, each with whether it lets things back in."""
    rules = []
    for line in (ROOT / ".dockerignore").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rules.append((line.lstrip("!").strip("/"), line.startswith("!")))
    return rules


def reaches_the_build(path: str) -> bool:
    """Docker's rule: a pattern matches a path or any directory above it, and the last pattern
    that matches decides."""
    parts = PurePosixPath(path).parts
    ancestors = [PurePosixPath(*parts[:n]) for n in range(1, len(parts) + 1)]
    sent = True
    for pattern, lets_in in ignore_rules():
        if any(a.full_match(pattern) for a in ancestors):
            sent = lets_in
    return sent


def copies(service: str) -> list[tuple[str, str]]:
    """The Dockerfile's COPY instructions that take files from the build context, as (source,
    destination). A copy from another stage (`--from=`) carries nothing of the repository's."""
    found = []
    dockerfile = ROOT / "services" / service / "Dockerfile"
    for line in dockerfile.read_text().splitlines():
        words = line.split()
        if not words or words[0] != "COPY" or any(w.startswith("--from") for w in words):
            continue
        *sources_, destination = [w for w in words[1:] if not w.startswith("--")]
        destination = destination.replace("${LAMBDA_TASK_ROOT}", LAMBDA_TASK_ROOT)
        found.extend((s, destination) for s in sources_)
    return found


def layout(service: str, into: Path) -> Path:
    """The files the image would hold, under `into`; answers the directory its `tokelo` package
    landed in, which is what the function runs from."""
    code_root: Path | None = None
    for source, destination in copies(service):
        origin = ROOT / source
        files = (
            [origin] if origin.is_file() else sorted(p for p in origin.rglob("*") if p.is_file())
        )
        for file in files:
            relative = file.relative_to(ROOT).as_posix()
            if not reaches_the_build(relative):
                continue
            if origin.is_file():
                target = into / destination.lstrip("/")
                if destination.endswith("/"):
                    target = target / file.name
            else:
                target = into / destination.lstrip("/") / file.relative_to(origin)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
        if source.rstrip("/") == "src/tokelo":
            code_root = (into / destination.lstrip("/")).parent
    assert code_root is not None, f"services/{service}/Dockerfile copies no src/tokelo"
    return code_root


def run_in(code_root: Path, script: str) -> subprocess.CompletedProcess[str]:
    """`script` with only the image's files importable: not the repository's `src`, and no
    TOKELO_LEGAL_ROOT pointing back at the repository's `docs`."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "TOKELO_LEGAL_ROOT")}
    return subprocess.run(
        [
            sys.executable,
            "-P",
            "-c",
            f"import sys; sys.path.insert(0, {str(code_root)!r})\n{script}",
        ],
        cwd=code_root,
        env=env,
        capture_output=True,
        text=True,
    )


# The images whose code reads the curated law at run time, and what it does with it. Nothing
# finds these for itself: a lane that starts citing the law in another image adds it here, or
# that image goes out without the law, as the ocr image did.
CITES_THE_LAW = {
    # The rule catalogue checks every section a rule cites when it loads (T032), at analysis.
    "ocr": "from tokelo.ocr import rules; rules.catalogue()",
    # Part 7 of a dossier reproduces each cited section's text (T043).
    "dossier": "from tokelo.core import sources; [sources.section(i).text for i in sources.ids()]",
}


@pytest.mark.req("REQ-006")
@pytest.mark.parametrize("service", sorted(CITES_THE_LAW))
def test_an_image_that_cites_the_law_carries_every_curated_section(service, tmp_path):
    code_root = layout(service, tmp_path)

    ran = run_in(
        code_root,
        f"{CITES_THE_LAW[service]}\n"
        "from tokelo.core import sources\n"
        "print(sources.root())\n"
        "print(','.join(sorted(sources.ids())))",
    )

    assert ran.returncode == 0, ran.stderr
    root, found = ran.stdout.splitlines()
    assert Path(root).is_relative_to(tmp_path), f"the law was read from outside the image: {root}"
    assert found.split(",") == sorted(sources.ids())


def test_the_layout_is_the_images_and_not_the_repositorys(tmp_path):
    """The check above is only worth something if it can fail: an image that copies the code
    alone finds no law, as the ocr image did."""
    code_root = tmp_path / "function"
    shutil.copytree(ROOT / "src" / "tokelo", code_root / "tokelo")

    ran = run_in(code_root, "from tokelo.core import sources; print(len(sources.ids()))")

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "0"


def test_dockerignore_is_read_as_docker_reads_it():
    assert reaches_the_build("src/tokelo/core/sources.py")
    assert reaches_the_build("web/src/main.tsx")
    assert not reaches_the_build("web/node_modules/react/index.js")
    assert not reaches_the_build("README.md")
    assert not reaches_the_build(".git/HEAD")
