#!/usr/bin/env bash
# gate.sh -- the one build script. Everything that decides "is this code good enough
# to leave my machine / to merge" runs here, and ONLY here.
#
#   .githooks/pre-push      -> runs this before a push
#   .github/workflows/ci.yml -> runs this on every pull request, and on every push to main
#
# That is the whole point of the file: the local gate and the pipeline cannot drift
# apart, because there is only one of them. (Curriculum 201, Build Scripts: a build
# that only works in one person's environment is not a build.)
#
# Usage:
#   bash scripts/gate.sh                          # sweep placeholders over the whole tree
#   bash scripts/gate.sh --changed-files <path>   # sweep only the paths listed in <path>
#   bash scripts/gate.sh --list                   # print what it would run, run nothing
#   bash scripts/gate.sh --install-deps           # install every project's deps (CI uses this)
#
# Exit codes: 0 = every applicable check ran and passed. 1 = something failed, or a
# check that should have run could not run. There is deliberately no third state --
# see "the skip rule" below.
#
# ---------------------------------------------------------------------------
# THE SKIP RULE (read this before you "fix" the script by making it lenient)
#
#   A check that did not run is a FAILED check, not a passed one.
#
# The gate never reports green because it found nothing to do. If a directory has a
# pyproject.toml but no usable interpreter, that is a broken environment and the push
# is blocked. If the whole repo has no project manifest at all but the commits being
# pushed contain source files, that is a misconfigured gate and the push is blocked.
# The only silent pass is a repo that genuinely has no code in it yet.
#
# The earlier version of this gate did the opposite -- it skipped anything it could not
# run, printed "Test gate passed", and let untested code through. That is the defect
# this file exists to make impossible.
# ---------------------------------------------------------------------------

set -u

# git quotes any path holding a non-ASCII byte ("caf\303\251.py") unless told not to, and
# a quoted path matches no file on disk -- it would drop out of every sweep silently.
git() { command git -c core.quotePath=false "$@"; }

# That setting is not enough on its own. A name holding a double quote, a backslash or a tab is
# still printed quoted ("q\"uote.py"), and it drops out the same way. -z prints every name as
# it is, so every list of files in this script is read through here, one path per line.
# tr runs in the C locale: a name need not be valid UTF-8, and BSD tr stops at a byte that isn't.
ls_files() { git ls-files -z "$@" | LC_ALL=C tr '\0' '\n'; }

root="$(git rev-parse --show-toplevel)"
cd "$root" || exit 1

changed_files_list=""
list_only=0
install_only=0

while [ $# -gt 0 ]; do
  case "$1" in
    --changed-files) changed_files_list="${2:-}"; shift 2 ;;
    --list)          list_only=1; shift ;;
    --install-deps)  install_only=1; shift ;;
    -h|--help)       sed -n '2,36p' "$0"; exit 0 ;;
    *) echo "gate.sh: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

fail=0             # the step in progress has failed; settle_step() moves it to failed_steps
failed_steps=()    # what the final report names
current_step="setup"
ran=0
manifests=0

# Packages with no test suite yet, each declared against the task ID that will close
# the gap: UNTESTED["apps/web"]="T031". Empty by default -- see check_node() and
# check_composer(). This is
# the AGENTS.md 2a "explicitly declared stub with a follow-up task" rule, applied to a
# whole package. An entry here does not make the gate pass quietly; it still reports
# the gap on every run.
declare -A UNTESTED=()

# Tunables for the checks below. They live here, not in CI or the hook, like everything else.
DUPLICATION_THRESHOLD=5   # max % of duplicated lines across the repo's source (jscpd)
JSCPD_VERSION=5.2.0       # pinned: npx fetches exactly this version, never "latest"
# php -l runs in this image when php isn't on PATH. Pinned by digest, and the PHP shared
# hosts run (8.3): a syntax check by a different PHP can pass code the host won't parse.
PHP_IMAGE="php:8.3-cli@sha256:f1ed6d1fd0aa769ab94ca307b9deaf55fbc18434315b70e319cd79078515cd2b"

# Committed lockfiles of the projects found, scanned together by vuln_scan().
LOCKFILES=()

say()  { printf '%s\n' "$*"; }
bad()  { printf '!! %s\n' "$*"; }

# Scratch directories the checks make, removed however the script ends.
TMP_DIRS=()
trap '[ "${#TMP_DIRS[@]}" -eq 0 ] || rm -rf "${TMP_DIRS[@]}"' EXIT

# Checks only ever set fail=1, and the step that was running gets the blame when the next one
# starts. in_step names a check that prints no heading of its own; step prints one too.
settle_step() {
  [ "$fail" -ne 0 ] || return 0
  failed_steps+=("$current_step")
  fail=0
}
in_step() { settle_step; current_step="$*"; }
step()    { in_step "$*"; printf '\n-> %s\n' "$*"; }

# True if anything failed, after printing what did. The output above can run to thousands of
# lines, so the last thing on screen is the list of what to go and look for.
report_failures() {  # $1 is the name in the banner
  settle_step
  [ "${#failed_steps[@]}" -gt 0 ] || return 1
  say ""
  say "== $1 FAILED =="
  printf '!! failed: %s\n' "${failed_steps[@]}"
  return 0
}

# Directories that can hold a project of their own. Root first, then the layout
# docs/project-structure.md describes, then the two flat layouts people actually use
# before the microservices split happens.
project_dirs() {
  printf '%s\n' "$root"
  for d in "$root"/services/* "$root"/apps/* "$root"/packages/* \
           "$root/backend" "$root/frontend" "$root/web" "$root/api"; do
    [ -d "$d" ] && printf '%s\n' "$d"
  done
}

# ---------------------------------------------------------------- Python ----
# Resolved in strict order, most-pinned first. A bare `python` on PATH is the LAST
# resort and never the assumption: on Debian/Ubuntu derivatives `python` does not
# exist at all (only `python3`), which is exactly how the old gate silently skipped
# every Python suite it was supposed to run.
# An array, so a repo path holding a space ("~/projects/Jozi Buddy") stays one word when the
# runner is invoked. As a string it split there, and every Python check failed to start.
py_runner=()      # how to invoke a tool, e.g. (uv run --frozen) or ("/path/.venv/bin/python" -m)
py_kind=""
py_venv=""        # the virtualenv the runner belongs to, when it is one

# Run a Python tool in $1, with the environment the tool expects.
#
# Picking the right interpreter is not enough for tools that *inspect* the
# environment rather than just importing from it -- pyright and pip-audit both do.
# Invoked as a bare `.venv/bin/python -m pyright`, pyright resolves imports against
# the system environment and reports phantom "could not be resolved" errors for
# packages that are plainly installed. Setting VIRTUAL_ENV is what `uv run` does for
# you, and what this reproduces.
pyrun() {
  local d="$1"; shift
  if [ -n "$py_venv" ]; then
    ( cd "$d" && VIRTUAL_ENV="$py_venv" PATH="$py_venv/bin:$PATH" "${py_runner[@]}" "$@" )
  else
    ( cd "$d" && "${py_runner[@]}" "$@" )
  fi
}

is_python_project() {
  [ -f "$1/pyproject.toml" ] || [ -f "$1/requirements.txt" ] || [ -f "$1/setup.py" ]
}

resolve_python() {
  local dir="$1"
  py_runner=(); py_kind=""; py_venv=""

  if [ -x "$dir/.venv/bin/python" ]; then
    py_runner=("$dir/.venv/bin/python" -m); py_kind="venv ($dir/.venv)"; py_venv="$dir/.venv"; return 0
  fi
  if [ -x "$root/.venv/bin/python" ]; then
    py_runner=("$root/.venv/bin/python" -m); py_kind="venv ($root/.venv)"; py_venv="$root/.venv"; return 0
  fi
  if [ -f "$dir/uv.lock" ] && command -v uv >/dev/null 2>&1; then
    py_runner=(uv run --frozen); py_kind="uv (uv.lock)"; return 0
  fi
  if command -v uv >/dev/null 2>&1 && [ -f "$dir/pyproject.toml" ]; then
    py_runner=(uv run); py_kind="uv"; return 0
  fi
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import pytest" >/dev/null 2>&1; then
      py_runner=("$candidate" -m); py_kind="$candidate on PATH"; return 0
    fi
  done
  return 1
}

check_python() {
  local dir="$1" rel="$2" rc
  is_python_project "$dir" || return 0
  manifests=$((manifests + 1))

  if ! resolve_python "$dir"; then
    in_step "python environment ($rel)"
    bad "$rel has a Python project but no usable interpreter."
    bad "   Tried: $dir/.venv, $root/.venv, uv, python3+pytest, python+pytest."
    bad "   Fix the environment -- a gate that cannot run is not a gate that passed."
    bad "   e.g.  uv venv .venv && uv pip install -e '.[dev]'"
    fail=1
    return 0
  fi
  say "   python: $py_kind"

  if [ "$list_only" -eq 1 ]; then say "   would run: ruff check, ruff format --check, pyright, pytest ($rel)"; return 0; fi

  # Static analysis is part of the gate, not a nicety. Code rots one commit at a
  # time (Curriculum 201, Code Analysis); the cheapest place to catch it is here.
  if pyrun "$dir" ruff --version >/dev/null 2>&1; then
    step "ruff check ($rel)"
    pyrun "$dir" ruff check . || fail=1
    step "ruff format --check ($rel)"
    pyrun "$dir" ruff format --check . || fail=1
    ran=$((ran + 1))
  else
    # The skip rule covers lint exactly as it covers tests. This used to print
    # "skipping lint" and carry on -- a skipped check reporting green.
    in_step "ruff ($rel)"
    bad "$rel has no ruff in its environment, so its lint and format checks cannot run."
    bad "   Add it as a dev dependency:  uv add --dev ruff   (or list it in requirements.txt)"
    fail=1
  fi

  # Type checking -- the tool pyrun() sets VIRTUAL_ENV for. It catches the call that
  # passes a str where the signature says int, which lint can't see and a test only
  # sees if someone thought to write that test.
  if pyrun "$dir" pyright --version >/dev/null 2>&1; then
    step "pyright ($rel)"
    pyrun "$dir" pyright || fail=1
    ran=$((ran + 1))
  else
    in_step "pyright ($rel)"
    bad "$rel has no pyright in its environment, so its type check cannot run."
    bad "   Add it as a dev dependency:  uv add --dev pyright   (or list it in requirements.txt)"
    fail=1
  fi

  step "pytest ($rel)"
  pyrun "$dir" pytest -q
  rc=$?
  if [ "$rc" -eq 5 ]; then
    # 5 == "no tests collected": nothing ran, so this is not a check that passed.
    bad "   pytest collected no tests in $rel -- a check that did not run is a failed check."
    bad "   If this package has behaviour, it needs tests."
    fail=1
  else
    ran=$((ran + 1))
    [ "$rc" -eq 0 ] || fail=1
  fi
}

# ------------------------------------------------------------------ Node ----
# The package manager is whatever the committed lockfile says it is, not npm by
# assumption. Running `npm run build` in a pnpm workspace either fails outright or
# silently resolves a different dependency tree than the one that was locked.
node_pm() {
  local dir="$1"
  if   [ -f "$dir/pnpm-lock.yaml" ] || [ -f "$root/pnpm-lock.yaml" ]; then echo pnpm
  elif [ -f "$dir/yarn.lock" ]      || [ -f "$root/yarn.lock" ];      then echo yarn
  elif [ -f "$dir/bun.lock" ] || [ -f "$dir/bun.lockb" ] \
       || [ -f "$root/bun.lock" ] || [ -f "$root/bun.lockb" ];        then echo bun
  else echo npm
  fi
}

# Does the package.json in $1 declare script $2? Ask package.json directly:
# `npm test --if-present` exits 0 when there is no test script at all, which reads
# as a pass.
has_script() {
  node -e 'const p=require(process.argv[1]);process.exit(p.scripts&&p.scripts[process.argv[2]]?0:1)' \
    "$1/package.json" "$2" 2>/dev/null
}

check_node() {
  local dir="$1" rel="$2" pm
  [ -f "$dir/package.json" ] || return 0
  manifests=$((manifests + 1))
  in_step "node environment ($rel)"

  pm="$(node_pm "$dir")"
  if ! command -v "$pm" >/dev/null 2>&1; then
    bad "$rel is locked to '$pm' (its lockfile says so) but '$pm' is not on PATH."
    bad "   Install it, or the gate cannot run this package's checks."
    fail=1
    return 0
  fi

  # node_modules is checked per directory, not at the repo root. A monorepo with
  # apps/web/node_modules and nothing at the root used to skip every JS suite.
  if [ ! -d "$dir/node_modules" ] && [ ! -d "$root/node_modules" ]; then
    bad "$rel has a package.json but no installed dependencies -- its suite cannot run."
    bad "   Run '$pm install' in $rel (or at the workspace root)."
    fail=1
    return 0
  fi

  if ! command -v node >/dev/null 2>&1; then
    bad "$rel has a package.json but node is not on PATH -- its suite cannot run."
    fail=1
    return 0
  fi

  local has_lint=no has_test=no has_build=no
  has_script "$dir" lint  && has_lint=yes
  has_script "$dir" test  && has_test=yes
  has_script "$dir" build && has_build=yes

  if [ "$list_only" -eq 1 ]; then
    say "   would run ($pm): $( [ "$has_lint" = yes ] && printf 'lint ' )$( [ "$has_test" = yes ] && printf 'test ' )$( [ "$has_build" = yes ] && printf 'build ' )($rel)"
    [ "$has_lint" = no ] && say "   (no 'lint' script -- would FAIL)"
    [ "$has_test" = no ] && say "   (no 'test' script -- would FAIL)"
    return 0
  fi

  # Static analysis runs before the tests, as it does for Python. The gate can't know
  # which JS tools a package uses, so the package declares them in its `lint` script
  # -- and a package without one fails, the same way a Python project without ruff does.
  if [ "$has_lint" = yes ]; then
    step "$pm run lint ($rel)"
    ( cd "$dir" && "$pm" run lint ) || fail=1
    ran=$((ran + 1))
  else
    in_step "$pm run lint ($rel)"
    bad "$rel declares no 'lint' script, so its code ships unanalysed."
    bad "   Add one that runs its static checks, e.g."
    bad "   \"lint\": \"eslint . && prettier --check . && tsc --noEmit\""
    fail=1
  fi

  if [ "$has_test" = yes ]; then
    step "$pm test ($rel)"
    ( cd "$dir" && "$pm" test ) || fail=1
    ran=$((ran + 1))
  else
    # Untested code is the thing the gate exists to stop. A package that declares no
    # test script does not "have no tests to run" -- it has tests nobody wrote.
    #
    # The single exception mirrors AGENTS.md 2a's rule for stubs: it is allowed only if
    # it has been *explicitly declared* against a follow-up task ID. Set UNTESTED in a
    # project-local block above, e.g.
    #     UNTESTED["apps/web"]="T031"
    # That keeps the gap loud on every single run and attached to a task somebody owns,
    # which is the opposite of silencing it with a fake "test" script.
    in_step "$pm test ($rel)"
    local declared="${UNTESTED[$rel]:-}"
    if [ -n "$declared" ]; then
      bad "$rel has no test suite -- declared, tracked as $declared."
      bad "   Its behaviour is unproven. This exemption is not a pass; close $declared."
    else
      bad "$rel declares no 'test' script, so its code ships unproven."
      bad "   Write the suite. If it genuinely cannot be written yet, the package is"
      bad "   BLOCKED, not done: add a task for it and declare it via UNTESTED[\"$rel\"]."
      fail=1
    fi
  fi

  if [ "$has_build" = yes ]; then
    step "$pm run build ($rel)"
    ( cd "$dir" && "$pm" run build ) || fail=1
    ran=$((ran + 1))
  fi
}

# ------------------------------------------------------------------- PHP ----
# PHP is often not a package at all: a few endpoints beside a static site, deployed to a
# shared host that parses them on the first request. So there are two checks. Every
# tracked .php file goes through `php -l` -- a syntax error otherwise surfaces as a 500 in
# production. And a directory with a composer.json is a package like any other: installed,
# with a test script the gate runs, or declared UNTESTED against a task.
php_files() {  # tracked PHP files that are the project's own (not vendored, not fixtures)
  ls_files -- '*.php' \
    | grep -Ev '(^|/)(docs|legacy|fixtures|mocks|__mocks__|testdata|node_modules|vendor)/' || true
}

php_lint() {
  local -a files
  mapfile -t files < <(php_files)
  [ "${#files[@]}" -gt 0 ] || return 0
  step "php -l (${#files[@]} PHP file(s), $(command -v php >/dev/null 2>&1 && echo "php on PATH" || echo "$PHP_IMAGE"))"
  local out rc=0
  # One PHP process per file, in one shell, so a failure names its file. php -l exits 255 on
  # a parse error; anything else non-zero means it didn't run, which fails just the same.
  local lint='for f in "$@"; do php -d display_errors=stderr -l "$f" >/dev/null || { echo "!! $f"; s=1; }; done; exit ${s:-0}'
  if command -v php >/dev/null 2>&1; then
    out="$( cd "$root" && bash -c "$lint" lint "${files[@]}" 2>&1 )" || rc=$?
  elif command -v docker >/dev/null 2>&1; then
    out="$(docker run --rm --network none -v "$root:/src:ro" -w /src "$PHP_IMAGE" \
             sh -c "$lint" lint "${files[@]}" 2>&1)" || rc=$?
  else
    bad "There are PHP files, but neither php nor docker is on PATH, so they can't be checked."
    bad "   Install PHP (the version the host runs), or Docker for the $PHP_IMAGE image."
    fail=1
    return 0
  fi
  ran=$((ran + 1))
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$out" | sed 's/^/   /'
    bad "PHP with a syntax error never reaches the host: fix the file(s) above."
    fail=1
  else
    say "   no syntax errors"
  fi
}

composer_has_test() {  # does composer.json in $1 declare a test script?
  ( cd "$1" && composer config scripts.test >/dev/null 2>&1 )
}

check_composer() {
  local dir="$1" rel="$2"
  [ -f "$dir/composer.json" ] || return 0
  manifests=$((manifests + 1))
  in_step "composer environment ($rel)"

  if ! composer --version >/dev/null 2>&1; then
    bad "$rel has a composer.json but Composer can't run (is it on PATH?) -- its suite cannot run."
    fail=1
    return 0
  fi
  if [ ! -d "$dir/vendor" ]; then
    bad "$rel has a composer.json but no installed dependencies -- its suite cannot run."
    bad "   Run 'composer install' in $rel."
    fail=1
    return 0
  fi

  local has_test=no
  composer_has_test "$dir" && has_test=yes
  if [ "$list_only" -eq 1 ]; then
    if [ "$has_test" = yes ]; then say "   would run (composer): test ($rel)"
    else say "   (no 'test' script in composer.json -- would FAIL)"
    fi
    return 0
  fi

  if [ "$has_test" = yes ]; then
    step "composer test ($rel)"
    ( cd "$dir" && composer test ) || fail=1
    ran=$((ran + 1))
  else
    # The same rule as check_node(): no test script is untested code, unless the package
    # is declared in UNTESTED against the task that will write its suite.
    in_step "composer test ($rel)"
    local declared="${UNTESTED[$rel]:-}"
    if [ -n "$declared" ]; then
      bad "$rel has no test suite -- declared, tracked as $declared."
      bad "   Its behaviour is unproven. This exemption is not a pass; close $declared."
    else
      bad "$rel declares no 'test' script in composer.json, so its code ships unproven."
      bad "   Write the suite (\"scripts\": {\"test\": \"phpunit\"}). If it genuinely cannot be"
      bad "   written yet, the package is BLOCKED: add a task and declare it via UNTESTED[\"$rel\"]."
      fail=1
    fi
  fi
}

# ------------------------------------------------- shell + workflow lint ----
# The gate, the hooks and CI are code too, and when they are wrong every other check is wrong
# with them. shellcheck reads the shell (every tracked *.sh, the hooks, and any tracked file
# that starts with a bash or sh #! line), each as the shell its #! line names, at warning level
# and up (unquoted variables, SC2086, are info level and not refused); actionlint reads the
# workflows, and the shell inside their run: steps. Each runs from PATH when it is installed,
# else from its image, pinned by digest so the same version runs everywhere. Neither, and the check fails: a hook that is
# never linted is how a broken hook reaches every clone.
SHELLCHECK_IMAGE="koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d"
ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"

docker_usable() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

shell_files() {  # tracked shell scripts, one per line
  local f first
  while IFS= read -r f; do
    [ -f "$root/$f" ] || continue
    case "$f" in
      *.sh|.githooks/*) printf '%s\n' "$f"; continue ;;
      *.*) continue ;;
    esac
    IFS= read -r first < "$root/$f" 2>/dev/null || continue
    case "$first" in
      '#!'*/bash*|'#!'*/sh|'#!'*/sh' '*|'#!'*'env bash'*|'#!'*'env sh'*) printf '%s\n' "$f" ;;
    esac
  done < <(ls_files)
}

shell_lint() {
  local -a files
  mapfile -t files < <(shell_files)
  [ "${#files[@]}" -gt 0 ] || return 0
  if [ "$list_only" -eq 1 ]; then say "-> would run: shellcheck on ${#files[@]} script(s)"; return 0; fi
  step "shellcheck (${#files[@]} script(s))"
  if command -v shellcheck >/dev/null 2>&1; then
    ( cd "$root" && shellcheck --severity=warning -- "${files[@]}" ) || fail=1
  elif docker_usable; then
    docker run --rm --network none -v "$root:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" \
      --severity=warning -- "${files[@]}" || fail=1
  else
    bad "shellcheck is not on PATH, and Docker isn't available to run $SHELLCHECK_IMAGE."
    bad "   Install it (apt install shellcheck / brew install shellcheck) or start Docker."
    fail=1
    return 0
  fi
  ran=$((ran + 1))
}

workflow_lint() {
  [ -n "$(git ls-files -- .github/workflows)" ] || return 0
  if [ "$list_only" -eq 1 ]; then say "-> would run: actionlint on .github/workflows"; return 0; fi
  step "actionlint (.github/workflows)"
  if command -v actionlint >/dev/null 2>&1; then
    ( cd "$root" && actionlint -no-color ) || fail=1
  elif docker_usable; then
    docker run --rm --network none -v "$root:/repo:ro" -w /repo "$ACTIONLINT_IMAGE" -no-color || fail=1
  else
    bad "actionlint is not on PATH, and Docker isn't available to run $ACTIONLINT_IMAGE."
    bad "   A broken workflow fails only once it reaches GitHub. Install actionlint"
    bad "   (go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12) or start Docker."
    fail=1
    return 0
  fi
  ran=$((ran + 1))
}

# ------------------------------------------------------------ doc links ----
# The docs are what the next reader -- a person or an AI -- builds to, and they point at each
# other constantly. A relative link to a file that was renamed or removed sends that reader to
# nothing. Every relative link in a tracked Markdown file must name a file git tracks (or a
# folder holding one): what is on this disk but not in git is not there for anyone else, and CI
# would refuse what this machine let through. Web links, #anchors and ?queries are not
# followed: GitHub's heading anchors depend on rules (punctuation, accents, repeated headings)
# a script would only guess at, and a wrong guess refuses a good push. Code (fenced or
# indented), inline code and HTML comments are not read. Templates are skipped: their links
# are placeholders.
#
# A template and the file setup makes from it stand for each other: a link to NAME.md resolves
# when NAME.template.md is tracked beside it (in the kit), and a link to NAME.template.md
# resolves when NAME.md is (in a project, where setup used the template up).

# The inline link targets of a Markdown file on stdin, one per line, as written.
md_link_targets() {
  awk '
    function run(x,   c, n) { c = substr(x, 1, 1); n = 0; while (substr(x, n + 1, 1) == c) n++; return n }
    {
      line = $0
      # HTML comments, across lines.
      out = ""
      while (1) {
        if (incomment) {
          e = index(line, "-->")
          if (e == 0) { line = ""; break }
          line = substr(line, e + 3); incomment = 0
        }
        s = index(line, "<!--")
        if (s == 0) { out = out line; break }
        out = out substr(line, 1, s - 1); line = substr(line, s + 4); incomment = 1
      }
      line = out
      # Fenced code: closed only by the same marker, at least as long. (No {n,} in these
      # patterns: not every awk reads them.)
      if (fence != "") {
        m = line; sub(/^ ? ? ?/, "", m); sub(/[ \t]*$/, "", m)
        if (m != "" && run(m) == length(m) && substr(m, 1, 1) == substr(fence, 1, 1) && length(m) >= length(fence)) fence = ""
        prevblank = 0; next
      }
      if (line ~ /^ ? ? ?(```|~~~)/) {
        m = line; sub(/^ ? ? ?/, "", m); fence = substr(m, 1, run(m)); next
      }
      # Indented code: four spaces or a tab, after a blank line or more code.
      if (line ~ /^(    |\t)/ && (prevblank || incode)) { incode = 1; next }
      incode = 0
      prevblank = (line ~ /^[ \t]*$/)
      gsub(/`[^`]*`/, "", line)
      while (match(line, /\]\((<[^>]*>|([^()[:space:]]|\([^()[:space:]]*\))+)([ \t]+"[^"]*")?\)/)) {
        t = substr(line, RSTART + 2, RLENGTH - 3)
        sub(/[ \t]+"[^"]*"$/, "", t)
        print t
        line = substr(line, RSTART + RLENGTH)
      }
    }'
}

# norm_path <path>: "." and ".." folded away, as plain text (the target need not exist). A
# result starting with ".." points above where the path started.
norm_path() {
  local part p out=() parts=()
  # Split on / with read, not by setting IFS for the function (Semgrep's ifs-tampering rule).
  IFS=/ read -r -a parts <<< "$1"
  for part in "${parts[@]}"; do
    case "$part" in
      ''|.) ;;
      ..) if [ "${#out[@]}" -gt 0 ] && [ "${out[-1]}" != .. ]; then unset 'out[-1]'; else out+=(..); fi ;;
      *) out+=("$part") ;;
    esac
  done
  part=""
  for p in "${out[@]}"; do part="${part:+$part/}$p"; done
  printf '%s\n' "$part"
}

# tracked_path <path from the repo root>: git tracks it, or a file under it.
tracked_path() {
  [ -n "$(git ls-files -- ":(literal)$1" 2>/dev/null | head -n 1)" ] && return 0
  [ -n "$(git ls-files -- ":(literal)${1%/}/" 2>/dev/null | head -n 1)" ]
}

doc_link_check() {
  local -a mds
  local md dir target path rel broken=0
  mapfile -t mds < <(ls_files -- '*.md' | grep -Ev '\.template\.md$' || true)
  [ "${#mds[@]}" -gt 0 ] || return 0
  if [ "$list_only" -eq 1 ]; then say "-> would run: markdown link check on ${#mds[@]} file(s)"; return 0; fi
  step "markdown link check (${#mds[@]} file(s))"
  for md in "${mds[@]}"; do
    [ -f "$root/$md" ] || continue
    dir="$(dirname "$md")"; [ "$dir" = . ] && dir=""
    while IFS= read -r target; do
      target="${target#<}"; target="${target%>}"
      case "$target" in ''|'#'*|[a-zA-Z]*:*) continue ;; esac   # anchors, web links, mailto:
      target="${target%%#*}"; target="${target%%\?*}"
      [ -n "$target" ] || continue
      # Markdown escapes (a\_b), then %XX: the backslashes go first, so printf reads only %XX.
      target="$(printf '%s' "$target" | sed 's/\\\(.\)/\1/g')"
      target="${target//\\/\\\\}"
      target="$(printf '%b' "${target//%/\\x}")"
      if [ "${target#/}" != "$target" ]; then rel="${target#/}"; else rel="${dir:+$dir/}$target"; fi
      rel="$(norm_path "$rel")"
      case "$rel" in
        ..|../*) bad "   $md -> $target (points outside the repository)"; broken=1; continue ;;
      esac
      tracked_path "$rel" && continue
      case "$rel" in
        *.template.md) tracked_path "${rel%.template.md}.md" && continue ;;
        *.md)          tracked_path "${rel%.md}.template.md" && continue ;;
      esac
      if [ -e "$root/$rel" ]; then
        bad "   $md -> $target (on this machine, but not in git: nobody else has it)"
      else
        bad "   $md -> $target (no such file)"
      fi
      broken=1
    done < <(md_link_targets < "$root/$md")
  done
  ran=$((ran + 1))
  if [ "$broken" -ne 0 ]; then
    bad "Broken relative links above. Fix the path, or the doc points its reader at nothing."
    fail=1
  else
    say "   every relative link resolves"
  fi
}

# ---------------------------------------------------------------- Gradle ----
# A Gradle build is checked through its own wrapper, never a Gradle someone happens to have
# installed: gradlew and gradle/wrapper/ pin the version, so they must be committed. `check`
# compiles, runs every test task and whatever verification the build adds. The JUnit reports
# it writes are what says tests ran, as the surefire reports are for Maven.
#
# A Gradle build is the nearest folder holding settings.gradle(.kts), from the project's folder
# up to the repo root, or the project's own folder when there is none. Each build runs once,
# from there: its subprojects are built by that run, wherever the build itself sits.
is_gradle_project() {
  [ -f "$1/settings.gradle.kts" ] || [ -f "$1/settings.gradle" ] \
    || [ -f "$1/build.gradle.kts" ] || [ -f "$1/build.gradle" ]
}

GRADLE_BUILT=()   # the builds already run, as paths from the repo root

gradle_build_of() {  # the Gradle build $1 belongs to, as an absolute path
  local d="$1"
  while :; do
    if [ -f "$d/settings.gradle" ] || [ -f "$d/settings.gradle.kts" ]; then printf '%s\n' "$d"; return 0; fi
    [ "$d" = "$root" ] || [ "$d" = / ] && break
    d="$(dirname "$d")"
  done
  printf '%s\n' "$1"
}

check_gradle() {
  local dir="$1" rel="$2" p f missing=0 marker tests declared
  is_gradle_project "$dir" || return 0
  manifests=$((manifests + 1))
  dir="$(gradle_build_of "$dir")"
  rel="${dir#"$root"/}"; [ "$rel" = "$dir" ] && rel="."
  case " ${GRADLE_BUILT[*]:-} " in
    *" $rel "*) say "   gradle: ${2} is part of the Gradle build at $rel, already run"; return 0 ;;
  esac
  GRADLE_BUILT+=("$rel")
  [ "$rel" = "${2}" ] || say "   gradle: ${2} is part of the Gradle build at $rel, run from there"
  p="${rel}/"; p="${p#./}"

  for f in gradlew gradle/wrapper/gradle-wrapper.properties gradle/wrapper/gradle-wrapper.jar; do
    if ! git ls-files --error-unmatch -- "$p$f" >/dev/null 2>&1; then
      in_step "gradle wrapper ($rel)"
      bad "$rel is a Gradle build but $p$f is not committed."
      missing=1
    fi
  done
  if [ "$missing" -eq 1 ]; then
    bad "   Commit the wrapper (gradle wrapper --gradle-version <the version PLAN.md pins>): the"
    bad "   gate runs ./gradlew, so the build uses the Gradle version the repo pins."
    fail=1
    return 0
  fi
  if ! command -v java >/dev/null 2>&1 && [ -z "${JAVA_HOME:-}" ]; then
    in_step "gradle environment ($rel)"
    bad "$rel is a Gradle build but there is no JDK (no java on PATH, no JAVA_HOME)."
    fail=1
    return 0
  fi
  if [ "$list_only" -eq 1 ]; then
    say "   would run (gradle): ./gradlew check ($rel)"
    return 0
  fi

  # Gradle skips a test task whose outputs are already there, and writes no new report. The
  # old reports go first, so the tests run and the count below is this run's.
  find "$dir" -type d -path '*/build/test-results' -prune -exec rm -rf {} + 2>/dev/null
  marker="$(mktemp)"
  step "./gradlew check ($rel)"
  # Through bash: a wrapper committed from Windows has often lost its executable bit.
  ( cd "$dir" && bash ./gradlew check --no-daemon --console=plain ) || fail=1
  ran=$((ran + 1))
  tests="$(find "$dir" -path '*/build/test-results/*' -name 'TEST-*.xml' -newer "$marker" -print0 2>/dev/null \
            | xargs -0 -r grep -ho '<testsuite [^>]*' 2>/dev/null \
            | grep -o ' tests="[0-9]*"' | grep -o '[0-9][0-9]*' | awk '{ s += $1 } END { print s + 0 }')"
  rm -f "$marker"
  if [ "$tests" -eq 0 ]; then
    declared="${UNTESTED[$rel]:-}"
    if [ -n "$declared" ]; then
      bad "$rel ran no tests -- declared, tracked as $declared."
      bad "   Its behaviour is unproven. This exemption is not a pass; close $declared."
    else
      bad "$rel built, but no test ran: Gradle wrote no JUnit report during this run."
      bad "   Code with no tests ships unproven. Write the suite; if it cannot be written yet,"
      bad "   the project is BLOCKED: add a task and declare it via UNTESTED[\"$rel\"]."
      fail=1
    fi
  else
    say "   $tests test(s) reported"
  fi
}

# ----------------------------------------------------------------- Maven ----
# A pom.xml is a project like any other: `mvn verify` compiles it and runs every test
# phase, so a red suite fails the push the same as a failing pytest. The project's own
# wrapper (mvnw) is used when it has one, because that is the Maven version it pinned.
#
# Maven has no lockfile, and a pom names direct dependencies only. So after the build the
# gate asks Maven itself for everything it resolved, across every module of the build, as a
# CycloneDX list, and vuln_scan() reads that. Handing the pom to the scanner instead misses
# whatever the direct dependencies pull in, and fails on a module that depends on a sibling.
CYCLONEDX_VERSION=2.9.1   # pinned: the cyclonedx-maven-plugin release that writes the list
MAVEN_BOMS=()             # one resolved dependency list per Maven build

# The modules the pom in $1 builds by default, as paths from the repo root, one per line, and
# theirs in turn. $2 is $1's own path from the root ("" for the root). Comments and profiles
# are cut out first: a module named only in a comment, or in a profile that is off by
# default, is not built by a plain `mvn verify`, and must not be treated as if it were.
maven_modules() {
  local pomdir="$1" prefix="$2" depth="${3:-0}" m
  [ -f "$pomdir/pom.xml" ] && [ "$depth" -lt 8 ] || return 0
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    printf '%s\n' "$prefix$m"
    maven_modules "$pomdir/$m" "$prefix$m/" "$((depth + 1))"
  done < <(awk '
    { s = s $0 "\n" }
    function cut(from, to,   i, j, rest) {
      while ((i = index(s, from)) > 0) {
        rest = substr(s, i + length(from)); j = index(rest, to)
        if (j == 0) { s = substr(s, 1, i - 1); break }
        s = substr(s, 1, i - 1) substr(rest, j + length(to))
      }
    }
    END {
      cut("<!--", "-->"); cut("<profiles>", "</profiles>")
      while (match(s, /<module>[^<]*<\/module>/)) {
        m = substr(s, RSTART + 8, RLENGTH - 17)
        gsub(/^[ \t\r\n]+|[ \t\r\n]+$/, "", m); sub(/^\.\//, "", m); sub(/\/+$/, "", m)
        print m
        s = substr(s, RSTART + RLENGTH)
      }
    }' "$pomdir/pom.xml")
}

check_maven() {
  local dir="$1" rel="$2" pom marker report bomdir bom declared slug
  local -a mvn=(mvn)
  [ -f "$dir/pom.xml" ] || return 0
  manifests=$((manifests + 1))

  pom="${rel}/pom.xml"; pom="${pom#./}"
  if ! git ls-files --error-unmatch -- "$pom" >/dev/null 2>&1; then
    in_step "pom.xml ($rel)"
    bad "$rel has a pom.xml that is not committed, so nobody else can build what is being"
    bad "   pushed, and CI cannot check it. Commit it."
    fail=1
  fi

  if [ "$rel" != "." ] && maven_modules "$root" "" | grep -Fxq -- "$rel"; then
    say "   maven: $rel is a module of the root pom, built and scanned by its run"
    return 0
  fi

  # Run through sh: a wrapper committed from Windows has often lost its executable bit.
  [ -f "$dir/mvnw" ] && mvn=(sh ./mvnw)
  if [ "${mvn[0]}" = mvn ] && ! command -v mvn >/dev/null 2>&1; then
    in_step "maven environment ($rel)"
    bad "$rel has a pom.xml but Maven (mvn) is not on PATH -- its suite cannot run."
    fail=1
    return 0
  fi
  if [ "$list_only" -eq 1 ]; then
    say "   would run (maven): ${mvn[*]} -B verify ($rel)"
    return 0
  fi

  step "${mvn[*]} -B verify ($rel)"
  marker="$(mktemp)"
  # A pom can switch its own tests off; these two switch them back on from outside it.
  ( cd "$dir" && "${mvn[@]}" -B -q -DskipTests=false -Dmaven.test.skip=false verify ) || fail=1
  ran=$((ran + 1))
  if [ "$fail" -eq 0 ]; then
    # A build with no tests exits 0 as well. The reports are what says tests ran: one written
    # during this run, by surefire (unit) or failsafe (integration), in any module.
    report="$(find "$dir" \( -path '*/target/surefire-reports/TEST-*.xml' \
                -o -path '*/target/failsafe-reports/TEST-*.xml' \) -newer "$marker" 2>/dev/null | head -n 1)"
    if [ -z "$report" ]; then
      declared="${UNTESTED[$rel]:-}"
      if [ -n "$declared" ]; then
        bad "$rel ran no tests -- declared, tracked as $declared."
        bad "   Its behaviour is unproven. This exemption is not a pass; close $declared."
      else
        bad "$rel built, but no test ran: Maven wrote no test report during this run."
        bad "   Code with no tests ships unproven. Write the suite; if it cannot be written yet,"
        bad "   the project is BLOCKED: add a task and declare it via UNTESTED[\"$rel\"]."
        fail=1
      fi
    fi
  fi
  rm -f "$marker"

  step "maven dependency list ($rel)"
  bomdir="$(mktemp -d)"; TMP_DIRS+=("$bomdir")
  slug="${rel//\//_}"; [ "$slug" = "." ] && slug="root"
  bom="$bomdir/maven-$slug.cdx.json"
  if ( cd "$dir" && "${mvn[@]}" -B -q \
         "org.cyclonedx:cyclonedx-maven-plugin:$CYCLONEDX_VERSION:makeAggregateBom" \
         -DoutputFormat=json -DoutputName=maven -DoutputDirectory="$bomdir" ) \
     && [ -s "$bomdir/maven.json" ]; then
    mv "$bomdir/maven.json" "$bom"
    # The project itself is the list's one entry when it depends on nothing, and a list of
    # nothing makes the scanner stop with an error instead of a result.
    if [ "$(grep -c '"purl"' "$bom")" -le 1 ]; then
      say "   $rel has no dependencies to scan"
    else
      say "   resolved by Maven: $(($(grep -c '"purl"' "$bom") - 1)) package(s)"
      MAVEN_BOMS+=("$bom")
    fi
  else
    bad "Maven could not list what $rel resolves to, so its dependencies cannot be scanned for"
    bad "   known vulnerabilities. A scan that did not run is a failed scan, not a clean one."
    fail=1
  fi
}

# ------------------------------------------------------------ file lists ----
# Paths travel through this script as newline-separated lists and are handed to grep and
# jscpd as arrays -- never as one space-joined string. The sweeps used to build
# `existing="$existing $root/$f"` and expand it unquoted, so a repo cloned into
# "~/projects/88 redesign" handed grep the fragments ".../88" and "redesign/src/x.html",
# grep could open neither, and both sweeps printed "clean" having read nothing.
#
# Read a newline-separated list of repo-relative paths on stdin; fill the array named
# $1 with the absolute path of each one that exists. Blank lines are dropped.
existing_files() {
  local -n _out="$1"
  local f
  _out=()
  while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$root/$f" ] && _out+=("$root/$f")
  done
  return 0
}

# One path per line cannot carry a name that itself holds a line break: it would arrive as
# two names that match nothing, and both sweeps would pass having skipped the file. Such a
# name fails the gate here instead. Nothing is counted for this: it is the sweeps' own input.
file_names() {
  local names lines
  names="$(git ls-files -z --cached --others --exclude-standard | LC_ALL=C tr -cd '\0' | wc -c)"
  lines="$(ls_files --cached --others --exclude-standard | wc -l)"
  [ "$names" -eq "$lines" ] && return 0
  in_step "file names"
  bad "A file name in this repo holds a line break, so the sweeps cannot list it:"
  command git ls-files --cached --others --exclude-standard | grep '^"' | grep -F '\n' | sed 's/^/     /'
  bad "   Rename it. A file the sweeps cannot read is a file nobody checked."
  fail=1
}

# ---------------------------------------------------------- placeholders ----
# AGENTS.md 2a is the kit's central rule -- nothing ships with a stub standing in for
# real work -- and until now nothing enforced it mechanically. This does.
#
# Note it sweeps the files being *pushed*, not `git diff --cached`: at pre-push time
# the index is empty, so a sweep written that way reads zero files and always passes.
placeholder_sweep() {
  step "placeholder sweep"
  local files rc
  local -a existing

  if [ -n "$changed_files_list" ] && [ -f "$changed_files_list" ]; then
    files="$(cat "$changed_files_list")"
  else
    # Untracked too: a freshly generated scaffold has nothing tracked yet, and a sweep of
    # `git ls-files` alone would read nothing and call it clean.
    say "   no change list given -- sweeping the whole tree, untracked files included"
    files="$(ls_files --cached --others --exclude-standard)"
  fi

  # Excluded: markdown and docs (prose about TODOs is not a TODO), fixtures and
  # mocks (stand-in data is their job), and the kit's own tooling -- the gate, and the
  # setup script that explains the no-placeholder rule to whoever runs it -- which
  # contain the very words being searched for and would otherwise always fail on
  # themselves. setup-project.sh used to be swept, and failed every new project's
  # first CI run on the word "TODO" in its own instructions.
  files="$(printf '%s\n' "$files" \
            | grep -Ev '^(docs/|legacy/|\.githooks/|\.github/|scripts/gate\.sh$|setup-project\.sh$)' \
            | grep -Ev '(^|/)(fixtures|mocks|__mocks__|testdata)/' \
            | grep -Ev '\.(md|txt|lock|svg|png|jpg|jpeg|gif|webp|ico)$' || true)"

  existing_files existing <<< "$files"
  # The sweep ran either way. Not counting it made a docs-only push report one check fewer
  # than a full run, which reads as a check having gone missing.
  ran=$((ran + 1))
  [ "${#existing[@]}" -gt 0 ] || { say "   nothing to sweep"; return 0; }

  # `XXX` is deliberately NOT in this list. It collides with real data far too often --
  # ISO 4217's "no currency" code, redacted digits, placeholder hostnames -- and a sweep
  # that cries wolf gets disabled, which costs more than the few stubs it would catch.
  #
  # grep exits 0 on a match, 1 on none, and 2 when it could not read a file. Only 1 is
  # clean: treating 2 as "no match" is how this sweep passed without reading anything.
  grep -InE '\b(TODO|FIXME|HACK|NotImplementedError|not implemented)\b' -- "${existing[@]}"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    bad "Placeholders found in the code being pushed."
    bad "   A task closed on a stub is BLOCKED, not done (AGENTS.md 2a)."
    bad "   If a stub is genuinely declared by the task, name its follow-up task ID beside it"
    bad "   and it stops being a placeholder -- but say so, do not hide it."
    fail=1
  elif [ "$rc" -ne 1 ]; then
    bad "The placeholder sweep could not read the files above (grep exit $rc)."
    bad "   A sweep that did not read the code is a failed sweep, not a clean one."
    fail=1
  else
    say "   clean"
  fi
}

# --------------------------------------------------------------- secrets ----
# Curriculum 200, Secrets and Password Management: a secret is anything that must stay
# private, and the cost of leaking one is not "fix and move on" -- once it is in git
# history it is compromised and must be rotated. So this runs before the push, which is
# the last moment it is still cheap.
#
# Pattern-matching cannot catch every secret and does not claim to. It catches the ones
# that actually leak in practice: a committed .env, a pasted key, a hardcoded password.
secret_sweep() {
  step "secret sweep"
  local files hits=0 rc found keylist
  local -a existing keyfiles

  if [ -n "$changed_files_list" ] && [ -f "$changed_files_list" ]; then
    files="$(cat "$changed_files_list")"
  else
    files="$(ls_files --cached --others --exclude-standard)"
  fi

  # Committed env files are the single most common leak, and no content check is
  # needed -- the filename is the finding. `.env.example` is the intended pattern.
  local envfiles
  envfiles="$(printf '%s\n' "$files" | grep -E '(^|/)\.env($|\.)' \
               | grep -Ev '\.(example|sample|template)$' || true)"
  if [ -n "$envfiles" ]; then
    bad "   env file(s) staged for push -- these belong in .gitignore, never in git:"
    printf '%s\n' "$envfiles" | sed 's/^/     /'
    hits=1
  fi

  # Key shapes are read almost everywhere, prose included: workflows and docs are where a
  # token gets pasted. The looser literal scan below stays out of them, because prose and
  # YAML legitimately say things like password: "...".
  keylist="$(printf '%s\n' "$files" \
            | grep -Ev '^(legacy/|\.githooks/|scripts/gate\.sh$)' \
            | grep -Ev '(^|/)__pycache__/' \
            | grep -Ev '\.(lock|svg|png|jpg|jpeg|gif|webp|ico)$' || true)"
  existing_files keyfiles <<< "$keylist"

  files="$(printf '%s\n' "$files" \
            | grep -Ev '^(docs/|legacy/|\.githooks/|\.github/|scripts/gate\.sh$)' \
            | grep -Ev '(^|/)__pycache__/' \
            | grep -Ev '\.(md|lock|svg|png|jpg|jpeg|gif|webp|ico)$' \
            | grep -Ev '(^|/)(tests?|__tests__|fixtures|mocks|__mocks__|testdata|examples?|samples?)/' \
            | grep -Ev '(\.(test|spec)\.[a-z]+|(^|/)test_[^/]*\.py|_test\.(py|go))$' || true)"
  existing_files existing <<< "$files"

  if [ "${#keyfiles[@]}" -gt 0 ]; then
    # Well-known key shapes. grep exit 2 means it could not read a file -- that fails the
    # sweep instead of passing it, as in the placeholder sweep. -I skips binaries, whose
    # "binary file matches" names no line anyone can act on.
    found="$(grep -InHE \
        -e '(AKIA|ASIA)[0-9A-Z]{16}' \
        -e 'sk-[A-Za-z0-9_-]{20,}' \
        -e 'ghp_[A-Za-z0-9]{36}' \
        -e 'xox[baprs]-[A-Za-z0-9-]{10,}' \
        -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' \
        -- "${keyfiles[@]}")"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      found="${found//"$root/"/}"
      printf '%s\n' "$found"
      bad "   the above matches the shape of a real credential (AWS / OpenAI / GitHub /"
      bad "   Slack token, or a private key). Rotate it -- assume it is already burned."
      name_hits "$found"
      hits=1
    elif [ "$rc" -ne 1 ]; then
      bad "   the credential scan could not read the files above (grep exit $rc)."
      hits=1
    fi
  fi

  if [ "${#existing[@]}" -gt 0 ]; then
    # Assignment of a secret-ish name to a literal that isn't obviously a placeholder or an
    # env lookup. That filter reads only the matched text: run over the file's path too, it
    # dropped every hit in a clone under a folder called "test", and in src/latest.py.
    found="$(grep -InHEi '(api[_-]?key|secret|password|passwd|token|credential)[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"']{12,}["'"'"']' \
        -- "${existing[@]}")"
    rc=$?
    if [ "$rc" -gt 1 ]; then
      bad "   the secret-literal scan could not read the files above (grep exit $rc)."
      hits=1
    fi
    found="${found//"$root/"/}"
    local benign='(example|placeholder|changeme|your[_-]?|xxx|\*{4,}|dummy|fake|test|sample|<|\$\{|process\.env|os\.environ|getenv)'
    local line text kept=""
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      text="${line#*:[0-9]*:}"
      [[ "${text,,}" =~ $benign ]] || kept+="$line"$'\n'
    done <<< "$found"
    found="${kept%$'\n'}"
    if [ -n "$found" ]; then
      printf '%s\n' "$found"
      bad "   a secret-looking literal is assigned in the code above."
      bad "   Read it from the environment instead, and rotate it if it is real."
      name_hits "$found"
      hits=1
    fi
  fi

  if [ "$hits" -ne 0 ]; then
    bad "Secrets must never enter git history -- rewriting the commit is not enough,"
    bad "   anything already pushed must be rotated. Fix before pushing."
    fail=1
  else
    say "   clean"
  fi
  ran=$((ran + 1))
}

# -------------------------------------------------------- secret history ----
# gitleaks, over every commit this branch is made of, not just the files being pushed. The
# sweep above reads only the tip of each changed file, so a key committed and then deleted two
# commits later passes it -- and is still in history, so it is still burned. gitleaks also
# knows far more key shapes than the sweep's five. A whole history takes about a second.
#
# It reads the history of the checked-out commit (HEAD), so the hook and CI scan the same
# commits and a branch answers for its own history, not for someone else's. A merge commit is
# compared with its first parent: git's default shows nothing for a merge, and a key added
# while resolving one would pass.
#
# A finding is never fixed by deleting the line: rotate the secret first (security-basics.md).
# A false positive is allowed in .gitleaks.toml at the repo root, as narrowly as it can be
# written and with its reason; a rotated secret that stays in old commits goes in
# .gitleaksignore by fingerprint. --exit-code 3 keeps "found a leak" apart from gitleaks' own
# exit 1, "could not scan".
gitleaks_scan() {
  step "secret history scan (gitleaks)"
  local rc out config="$root/.gitleaks.toml" allowed ignored
  local args=(--redact --no-banner --no-color --exit-code 3)

  if ! command -v gitleaks >/dev/null 2>&1; then
    bad "gitleaks is not on PATH, so git history cannot be scanned for secrets."
    bad "   Install it: https://github.com/gitleaks/gitleaks#installing"
    bad "   e.g.  go install github.com/zricethezav/gitleaks/v8@v8.30.1"
    fail=1
    return 0
  fi

  if ! git rev-parse -q --verify HEAD >/dev/null 2>&1; then
    say "   no commits yet -- there is no history to scan"
    ran=$((ran + 1))
    return 0
  fi

  # A shallow clone holds the last commit or two. Scanning it would report a clean history
  # having read almost none of it.
  if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = true ]; then
    bad "This clone is shallow, so most of the history is not here to scan."
    bad "   Fetch the rest:  git fetch --unshallow   (in CI: actions/checkout with fetch-depth: 0)"
    fail=1
    return 0
  fi

  if [ -f "$config" ]; then
    # A config replaces gitleaks' own rules unless it extends them. One that doesn't, an empty
    # file included, leaves the scan with nothing to look for, and it reports clean.
    if ! grep -Eq '^[[:space:]]*useDefault[[:space:]]*=[[:space:]]*true' "$config"; then
      bad ".gitleaks.toml does not extend gitleaks' own rules, so it would switch them all off."
      bad "   Start it with:   [extend]"
      bad "                    useDefault = true"
      fail=1
      return 0
    fi
    args+=(--config "$config")
    allowed="$(grep -Ec '^[[:space:]]*\[\[?allowlists?\]?\]' "$config" || true)"
    [ "$allowed" -gt 0 ] && bad "   allowed: $allowed allowlist(s) in .gitleaks.toml -- each one is a place the scan does not look."
  fi
  if [ -f "$root/.gitleaksignore" ]; then
    ignored="$(grep -Evc '^[[:space:]]*(#|$)' "$root/.gitleaksignore" || true)"
    [ "$ignored" -gt 0 ] && bad "   accepted: $ignored finding(s) in .gitleaksignore -- rotated secrets that stay in old commits."
  fi

  out="$(mktemp)"
  # The config is this repo's or gitleaks' own, never one a variable on this machine points at.
  env -u GITLEAKS_CONFIG -u GITLEAKS_CONFIG_TOML \
    gitleaks git "${args[@]}" --log-opts="--full-history --diff-merges=first-parent HEAD" "$root" 2>&1 | tee "$out"
  rc=${PIPESTATUS[0]}
  ran=$((ran + 1))
  if [ "$rc" -eq 3 ]; then
    bad "gitleaks found secrets in git history (above, redacted). Rotate each one first --"
    bad "   it is burned whether or not the commit is rewritten. Then, and only for a false"
    bad "   positive, allow it in .gitleaks.toml with the reason."
    fail=1
  elif [ "$rc" -ne 0 ]; then
    bad "gitleaks could not complete (exit $rc). A scan that did not run is a failed scan."
    fail=1
  elif grep -Eq '(^|[^0-9])0 commits scanned|(^| )ERR( |$)' "$out"; then
    # gitleaks exits 0 when the git command under it fails: it scans nothing and says clean.
    bad "gitleaks read no history (see above), so nothing was scanned. That is a failed scan."
    bad "   The scan needs git 2.31 or newer."
    fail=1
  fi
  rm -f "$out"
}

# Name the files behind grep -H output ("path:line:text") in the !! block.
name_hits() {
  local f
  while IFS= read -r f; do
    bad "   in: $f"
  done < <(printf '%s\n' "$1" | sed -E 's/:[0-9]+:.*$//' | sort -u)
}

# ------------------------------------------------------------- lockfiles ----
# Echo the committed lockfile pinning $1's dependencies of kind $2 (py | node | php): the
# directory's own, else the workspace root's. Committed only -- CI's install step
# generates a lockfile when none exists, and a generated one pins nothing anyone
# reviewed. requirements.txt counts only in the project's own directory, and only
# when requirements_pinned() says every line is an == pin, the only form exact enough to scan.
requirements_pinned() {
  # Comments, blank lines and option lines (-r, -e, --hash continuations) pin nothing and
  # loosen nothing. Whatever is left must read name==version, with an optional env marker.
  # A file with nothing left, only -r or -e lines say, pins nothing and is no lockfile.
  local reqs
  reqs="$(sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*\\$//' "$1" \
    | grep -v '^$' | grep -v '^-')"
  [ -n "$reqs" ] || return 1
  ! printf '%s\n' "$reqs" \
    | grep -Evq '^[A-Za-z0-9._-]+(\[[^]]*\])?[[:space:]]*==[[:space:]]*[^*,;[:space:]]+[[:space:]]*(--[^[:space:]]+[[:space:]]*)*(;.*)?$'
}

committed_lockfile() {
  local dir="$1" kind="$2" d f names path
  for d in "$dir" "$root"; do
    if [ "$kind" = py ]; then
      names="uv.lock poetry.lock pdm.lock Pipfile.lock"
      [ "$d" = "$dir" ] && names="$names requirements.txt"
    elif [ "$kind" = php ]; then
      names="composer.lock"
    else
      names="pnpm-lock.yaml yarn.lock bun.lock package-lock.json npm-shrinkwrap.json"
    fi
    for f in $names; do
      path="${d#"$root"}"; path="${path#/}"; path="${path:+$path/}$f"
      if git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
        [ "$f" = requirements.txt ] && ! requirements_pinned "$root/$path" && continue
        printf '%s\n' "$path"; return 0
      fi
    done
  done
  return 1
}

# Every project needs one. Without it there is nothing exact to scan for vulnerabilities,
# and nothing reproducible to install (architecture-defaults.md section 5) -- so a
# missing lockfile fails here rather than letting the scan quietly cover less.
# Every committed gradle.lockfile in the Gradle build at $1 (one per project of a multi-project
# build), added to the scan's list. False when the build has none.
gradle_lockfiles() {
  local build="$1" rel lock found=1
  rel="${build#"$root"/}"; [ "$rel" = "$build" ] && rel=""
  while IFS= read -r lock; do
    [ -n "$lock" ] || continue
    found=0
    case " ${LOCKFILES[*]:-} " in *" $lock "*) ;; *) LOCKFILES+=("$lock") ;; esac
  done < <(ls_files -- "${rel:-.}" | grep -E '(^|/)gradle\.lockfile$' || true)
  return "$found"
}

collect_lockfiles() {
  local dir="$1" rel="$2" kind lock
  for kind in py node php gradle; do
    if [ "$kind" = py ]; then is_python_project "$dir" || continue
    elif [ "$kind" = php ]; then [ -f "$dir/composer.json" ] || continue
    elif [ "$kind" = gradle ]; then
      is_gradle_project "$dir" || continue
    else [ -f "$dir/package.json" ] || continue
    fi
    if [ "$kind" = gradle ]; then
      gradle_lockfiles "$(gradle_build_of "$dir")" || {
        in_step "lockfile ($rel)"
        bad "$rel is in a Gradle build with no committed gradle.lockfile, so its dependencies cannot be scanned."
        bad "   Turn on dependency locking (dependencyLocking { lockAllConfigurations() }), run"
        bad "   './gradlew dependencies --write-locks', and commit the gradle.lockfile files it writes."
        fail=1
      }
    elif lock="$(committed_lockfile "$dir" "$kind")"; then
      case " ${LOCKFILES[*]:-} " in *" $lock "*) ;; *) LOCKFILES+=("$lock") ;; esac
    else
      in_step "lockfile ($rel)"
      bad "$rel has no committed lockfile, so its dependencies cannot be scanned for known vulnerabilities."
      if [ "$kind" = py ]; then
        bad "   Create one with  uv lock  (or pin every line of requirements.txt with ==), and commit it."
      elif [ "$kind" = php ]; then
        bad "   Run 'composer install' and commit the composer.lock it writes."
      else
        bad "   Run '$(node_pm "$dir") install' and commit the lockfile it writes."
      fi
      fail=1
    fi
  done
}

# ------------------------------------------------------- vulnerabilities ----
# Every committed lockfile, checked against OSV (which aggregates the GitHub, PyPI and
# other advisory feeds). Unlike every other check here, the result can change while the
# code doesn't: an advisory published tonight fails tomorrow's push on a branch nobody
# touched. That is the point -- a vulnerable dependency is exactly as vulnerable in
# unchanged code.
#
# Exemptions live in osv-scanner.toml at the repo root, one [[IgnoredVulns]] block each,
# under the same rule as UNTESTED: the reason names the task that will close it, and every
# run prints it. A task is a TASKS.md ID (T045) or, where the work is tracked in GitHub
# issues, an issue: "#45: ..." at the start of the reason, or "issue #45" anywhere in it. A
# bare #45 elsewhere is not enough -- "#000000" and "CVSS #3" are not issues. An ignoreUntil
# date makes an exemption expire on its own.
osv_exemptions() {   # prints "id<TAB>reason" per [[IgnoredVulns]] block of $1
  awk '
    function flush() { if (inblock) printf "%s\t%s\n", id, reason; inblock = 0; id = ""; reason = "" }
    /^[[:space:]]*\[\[IgnoredVulns\]\]/ { flush(); inblock = 1; next }
    /^[[:space:]]*\[/                   { flush(); next }
    inblock && /^[[:space:]]*id[[:space:]]*=/     { v = $0; sub(/^[^=]*=[[:space:]]*/, "", v); gsub(/"/, "", v); id = v }
    inblock && /^[[:space:]]*reason[[:space:]]*=/ { v = $0; sub(/^[^=]*=[[:space:]]*/, "", v)
                                                     # The quoted value only: a comment after it is not the reason.
                                                     if (match(v, /^"[^"]*"/)) v = substr(v, 2, RLENGTH - 2); else gsub(/"/, "", v)
                                                     reason = v }
    END { flush() }
  ' "$1"
}

vuln_scan() {
  step "dependency vulnerability scan (osv-scanner)"
  local config="$root/osv-scanner.toml" lock id reason rc
  local args=()

  if ! command -v osv-scanner >/dev/null 2>&1; then
    bad "osv-scanner is not on PATH, so dependencies cannot be checked for known vulnerabilities."
    bad "   Install it: https://google.github.io/osv-scanner/installation/"
    bad "   e.g.  go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1"
    fail=1
    return 0
  fi

  if [ -f "$config" ]; then
    args+=(--config "$config")
    while IFS=$'\t' read -r id reason; do
      if printf '%s' "$reason" | grep -qE '(\bT[0-9]+\b|^#[0-9]+\b|\b[Ii]ssues?[ /]?#?[0-9]+\b)'; then
        bad "   accepted: $id -- $reason"
      else
        bad "   $id is ignored in osv-scanner.toml, but its reason names no task."
        bad "   An exemption nobody owns is a vulnerability nobody fixes: reason = \"T0nn: ...\""
        bad "   (or \"#nn: ...\" / \"issue #nn\" where the work is tracked in GitHub issues)."
        fail=1
      fi
    done < <(osv_exemptions "$config")
  fi

  # Everything scanned here is already a full set of pinned packages -- a lockfile, or the list
  # Maven resolved -- so osv-scanner must not re-resolve it. Without this it resolves a pinned
  # requirements.txt through deps.dev, and one version deps.dev doesn't know yet aborts the
  # extraction: 0 packages scanned, exit 127.
  args+=(--no-resolve)
  for lock in ${LOCKFILES[@]+"${LOCKFILES[@]}"} ${MAVEN_BOMS[@]+"${MAVEN_BOMS[@]}"}; do
    case "$lock" in /*) args+=(-L "$lock") ;; *) args+=(-L "$root/$lock") ;; esac
  done
  [ "${#LOCKFILES[@]}" -gt 0 ] && say "   lockfiles: ${LOCKFILES[*]}"
  [ "${#MAVEN_BOMS[@]}" -gt 0 ] && say "   maven: ${#MAVEN_BOMS[@]} resolved dependency list(s)"

  osv-scanner scan source "${args[@]}"
  rc=$?
  ran=$((ran + 1))
  if [ "$rc" -eq 1 ]; then
    bad "Known vulnerabilities in the dependencies above. Upgrade to the fixed version --"
    bad "   or, only if none exists yet, declare it in osv-scanner.toml against a task."
    fail=1
  elif [ "$rc" -ne 0 ]; then
    bad "osv-scanner could not complete (exit $rc): see its output above. A scan that did not"
    bad "   run is a failed scan, not a clean one."
    fail=1
  fi
}

# ------------------------------------------------------------ duplication ----
# Copy-paste across the whole repo, measured by jscpd. AI assistants produce a local copy
# of logic far more readily than they reuse the shared version, and a multi-service repo
# hides the copy well: the same helper pasted into services/a and services/b passes every
# per-service check. So this runs once over all tracked source, and fails when duplicated
# lines exceed DUPLICATION_THRESHOLD percent.
#
# Not counted: tests (repeated, explicit setup is normal there), fixtures and mocks,
# vendored or built trees, and shadcn/ui's components/ui/ -- copied in from a registry and
# alike by design. Nor type declarations (*.d.ts): they are generated from a contract and
# repeat its shapes by construction, so the copy is in the generator's input, not in them.
# A deliberate copy is marked in the code, with the reason beside it:
#     # jscpd:ignore-start -- <why this copy is intended>
#     # jscpd:ignore-end
duplication_check() {
  step "duplication check (jscpd $JSCPD_VERSION, threshold $DUPLICATION_THRESHOLD%)"
  local out rc
  local -a files

  mapfile -t files < <(ls_files \
            | grep -E '\.(py|ts|tsx|js|jsx|mjs|cjs|go|rs|java|rb|php|c|cc|cpp|h|hpp|cs|kt|swift)$' \
            | grep -Ev '(^|/)(docs|legacy|fixtures|mocks|__mocks__|testdata|node_modules|vendor|dist|build|tests?|__tests__)/' \
            | grep -Ev '(^|/)components/ui/' \
            | grep -Ev '\.d\.ts$' \
            | grep -Ev '(\.(test|spec)\.[a-z]+|(^|/)test_[^/]*\.py|_test\.(py|go))$' || true)
  if [ "${#files[@]}" -eq 0 ]; then
    say "   no source files to compare"
    ran=$((ran + 1))
    return 0
  fi

  if ! command -v npx >/dev/null 2>&1; then
    bad "npx is not on PATH, so the duplication check (jscpd) cannot run. Install Node.js."
    fail=1
    return 0
  fi

  out="$(mktemp)"
  ( cd "$root" && npx --yes "jscpd@$JSCPD_VERSION" --threshold "$DUPLICATION_THRESHOLD" \
      --reporters console --no-colors "${files[@]}" ) 2>&1 | tee "$out"
  rc=${PIPESTATUS[0]}
  ran=$((ran + 1))
  if [ "$rc" -ne 0 ]; then
    if grep -q 'too many duplicates' "$out"; then
      bad "Duplicated code is over the threshold. Reuse the shared version instead of copying it,"
      bad "   or mark a deliberate copy with jscpd:ignore-start / jscpd:ignore-end and a reason."
    else
      bad "jscpd could not run (exit $rc) -- see above. A check that did not run is a failed check."
    fi
    fail=1
  fi
  rm -f "$out"
}

# ---------------------------------------------------------------- install ---
# CI installs dependencies by calling `gate.sh --install-deps`, so the installer walks
# exactly the directories project_dirs() lists and uses exactly the package manager
# check_node() will. It used to be a loop in ci.yml with its own directory list, and
# the two drifted: CI never installed a frontend/ package that the checks then failed
# for having no node_modules. The pre-push hook never calls this -- locally, a missing
# install is yours to fix, and the checks say so rather than fixing it behind your back.
install_deps() {
  local dir="$1" rel="$2" pm

  if is_python_project "$dir"; then
    manifests=$((manifests + 1))
    step "install Python dependencies ($rel)"
    if ! command -v uv >/dev/null 2>&1; then
      bad "   uv is not on PATH -- cannot install $rel's dependencies."
      fail=1
    elif [ -f "$dir/pyproject.toml" ]; then
      ( cd "$dir" && { uv sync --frozen || uv sync; } ) || fail=1
    elif [ -f "$dir/requirements.txt" ]; then
      # The Python check demands ruff, pyright and pytest, which a project with a separate
      # dev file keeps there.
      local -a reqs=(-r requirements.txt)
      [ -f "$dir/requirements-dev.txt" ] && reqs+=(-r requirements-dev.txt)
      ( cd "$dir" && { [ -d .venv ] || uv venv .venv; } && uv pip install "${reqs[@]}" ) || fail=1
    else
      ( cd "$dir" && { [ -d .venv ] || uv venv .venv; } && uv pip install -e . ) || fail=1
    fi
  fi

  if [ -f "$dir/package.json" ]; then
    manifests=$((manifests + 1))
    pm="$(node_pm "$dir")"
    step "$pm install ($rel)"
    if ! command -v "$pm" >/dev/null 2>&1; then
      bad "   $rel is locked to '$pm' (its lockfile says so) but '$pm' is not on PATH."
      fail=1
    elif [ "$pm" = npm ]; then
      ( cd "$dir" && { npm ci || npm install; } ) || fail=1
    else
      ( cd "$dir" && "$pm" install ) || fail=1
    fi
  fi

  if [ -f "$dir/composer.json" ]; then
    manifests=$((manifests + 1))
    step "composer install ($rel)"
    if ! composer --version >/dev/null 2>&1; then
      bad "   $rel has a composer.json but Composer can't run (is it on PATH?)."
      fail=1
    else
      ( cd "$dir" && composer install --no-interaction ) || fail=1
    fi
  fi
}

# ------------------------------------------------------------- the hook -----
# The gate only guards a push when the pre-push hook runs it, and git says nothing when there
# is no hook: a clone where nobody ran install-hooks.sh, or one whose hooks path points at a
# folder that has since moved. Running the gate by hand is the one moment that can be noticed.
# A note, not a failure: CI has no hook and needs none.
hook_note() {
  [ -z "${CI:-}" ] || return 0
  local path dir
  path="$(git config core.hooksPath 2>/dev/null || true)"
  case "$path" in
    "") say "note: this clone has no core.hooksPath, so its pushes are not gated. Run: bash install-hooks.sh"
        return 0 ;;
    /*) dir="$path" ;;
    *)  dir="$root/$path" ;;
  esac
  [ -f "$dir/pre-push" ] && return 0
  # A linked worktree of a project that keeps the kit out of git has no hooks folder of its own.
  say "note: core.hooksPath is '$path', and there is no pre-push hook there, so pushes from here"
  say "      are not gated. Run: bash install-hooks.sh   (in the main checkout, for a worktree)"
}

# ------------------------------------------------------------------ run -----
# A repo with no commit yet has no HEAD to name, and saying so beats git's own error for it.
say "== gate: $(git symbolic-ref --short -q HEAD || echo "detached HEAD") @ $(git rev-parse --short -q --verify HEAD || echo "no commits yet") =="

[ "$install_only" -eq 1 ] || hook_note

while IFS= read -r dir; do
  rel="${dir#"$root"/}"
  [ "$rel" = "$dir" ] && rel="."
  if [ "$install_only" -eq 1 ]; then
    install_deps "$dir" "$rel"
  else
    check_python      "$dir" "$rel"
    check_node        "$dir" "$rel"
    check_composer    "$dir" "$rel"
    check_maven       "$dir" "$rel"
    check_gradle      "$dir" "$rel"
    collect_lockfiles "$dir" "$rel"
  fi
done < <(project_dirs)

if [ "$install_only" -eq 1 ]; then
  report_failures "dependency install" && exit 1
  say ""
  say "== dependencies installed for $manifests project manifest(s) =="
  exit 0
fi

# --list stops here, before the sweeps. It used to run both of them and then report
# "nothing was executed".
if [ "$list_only" -eq 1 ]; then
  say ""
  say "-> would run: placeholder sweep, secret sweep, secret history scan (gitleaks)"
  command -v gitleaks >/dev/null 2>&1 || say "   (gitleaks not on PATH -- would FAIL)"
  shell_lint; workflow_lint; doc_link_check
  php_count="$(php_files | grep -c . || true)"
  [ "$php_count" -gt 0 ] && say "-> would run: php -l on $php_count PHP file(s)"
  if [ "$manifests" -gt 0 ]; then
    say "-> would run: dependency vulnerability scan over: ${LOCKFILES[*]:-(no committed lockfiles)}, and what Maven resolves for any pom.xml"
    command -v osv-scanner >/dev/null 2>&1 || say "   (osv-scanner not on PATH -- would FAIL)"
    say "-> would run: duplication check (jscpd $JSCPD_VERSION, threshold $DUPLICATION_THRESHOLD%)"
    command -v npx >/dev/null 2>&1 || say "   (npx not on PATH -- would FAIL)"
  fi
  say ""
  say "(--list: no checks were run. $manifests project manifest(s) found.)"
  exit 0
fi

file_names
placeholder_sweep
secret_sweep
gitleaks_scan
php_lint
shell_lint
workflow_lint
doc_link_check

# Both look at the whole repo rather than one project, so they run once, and only once
# there is a project to look at.
if [ "$manifests" -gt 0 ]; then
  if [ "${#LOCKFILES[@]}" -gt 0 ] || [ "${#MAVEN_BOMS[@]}" -gt 0 ]; then vuln_scan; fi
  duplication_check
fi

# Secret Realm: its own checks (requirements, traceability...). Its one line in this file.
[ -f "$root/scripts/realm/checks.sh" ] && . "$root/scripts/realm/checks.sh"

# --- the two ways a gate lies about being green ----------------------------
if [ "$manifests" -eq 0 ]; then
  # No project manifest anywhere. Fine for a scaffold-only repo; NOT fine if the
  # commits being pushed contain source code, because then real code is going in
  # entirely unchecked and the gate would otherwise say "passed".
  code=""
  if [ -n "$changed_files_list" ] && [ -f "$changed_files_list" ]; then
    code="$(grep -E '\.(py|ts|tsx|js|jsx|go|rs|java|rb|php|c|cc|cpp|h|hpp|cs|kt|swift)$' \
              "$changed_files_list" || true)"
  fi
  if [ -n "$code" ]; then
    bad "Source files are being pushed, but this repo has no project manifest"
    bad "   (no pyproject.toml / requirements.txt / package.json / composer.json / pom.xml /"
    bad "   Gradle build anywhere the gate looks)."
    bad "   The gate cannot check this code, so it will not pretend to have checked it."
    bad "   Add the manifest, or add this directory to project_dirs() in scripts/gate.sh."
    printf '%s\n' "$code" | sed 's/^/     /'
    exit 1
  fi
  say ""
  say "No project manifests yet -- scaffold-only repo, nothing to build. The sweeps ran."
fi
# There is no "manifests found, zero checks ran" case to catch here: the sweeps always count,
# and every way a project's own checks can fail to run sets fail=1 where it happens, by name.

report_failures "gate" && exit 1

say ""
say "== gate passed ($ran check(s) run across $manifests project(s)) =="
exit 0

# kit: SecretRealm c3be7f2ccbf9578c295a8180e2101e6af8e24e03
