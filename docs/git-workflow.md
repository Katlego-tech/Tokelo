# Git workflow

The point: **`main` is always green and demo-ready**, and the *only* way code reaches `main` is a
**reviewed, CI-green Pull Request** — never a direct push.

## The rule

> **Nobody pushes directly to `main`. All work happens on branches and merges via Pull Request, only
> after the gate runs clean and tests pass.**

The one common exception: the **initial scaffold commit** (this kit, filled in) is pushed straight to
`main` once, to seed the repo. The hook blocks that too, so the seed push is the one legitimate use
of `--no-verify`:

```bash
git push -u origin main --no-verify    # once, to seed an empty repo
```

From that point on, direct pushes are disabled (local hook + CI + server-side branch protection) and
`--no-verify` goes back to being an emergency measure you announce in STATUS.md.

## Branch model

- **`main`** — protected. Only updated by merging a PR. Always green, always demo-able.
- **Feature branches** — all real work: `feat/<lane>` (e.g. `feat/parser`) · `fix/<thing>` ·
  `docs/<thing>` · `chore/<thing>`.

## The loop (every change)

1. Read [STATUS.md](../STATUS.md), pick/confirm a task in [TASKS.md](../TASKS.md), claim your
   **lane** in STATUS.md.
2. `git switch -c feat/<lane>` — branch off fresh `main`.
3. Build the change **with its tests**.
4. `git push -u origin feat/<lane>` — the **pre-push hook runs the tests** and **blocks the push if
   they fail** (and blocks any attempt to push straight to `main`).
5. Open a **Pull Request into `main`**.
6. **Wait for green CI** + the review: another contributor in team mode, a fresh AI reviewer in
   [solo mode](#solo-mode) ([AGENTS.md](../AGENTS.md) §4).
7. **Merge the PR.** Tick the task `[x]` in TASKS.md, update STATUS.md (+ Log line).
8. Delete the branch. `git switch main && git pull`.

## Merge requirements (all must be true before merging a PR)

- ✅ CI green on the branch/PR.
- ✅ Tests pass (the pre-push hook proved it locally too).
- ✅ Reviewed — by another contributor (team mode), or by a fresh AI reviewer whose findings are
  posted on the PR ([solo mode](#solo-mode)).
- ✅ Task ticked in TASKS.md; STATUS.md updated.
- ✅ No unresolved conflicts with `main`.

## Three layers of "no direct push to main"

1. **Local pre-push hook** (`.githooks/pre-push`) — refuses to push to `main`/`master` and runs the
   gate. Enable once per clone — and note that this is per *clone*, not per repo: `core.hooksPath`
   lives in `.git/config`, which is never cloned, so every contributor runs this themselves or they
   silently have no gate at all:
   ```bash
   bash install-hooks.sh
   ```
   The installer sets the config, then fires the hook once to prove it actually rejects a push to
   `main`. A gate nobody has watched fire is indistinguishable from no gate.
2. **CI** (`.github/workflows/ci.yml`) — runs the *same* `scripts/gate.sh` on every push and PR, on
   hardware nobody can configure their way around.
3. **Server-side branch protection** (GitHub/GitLab/etc.) — the real authority, since layer 1 is
   opt-in and bypassable. Turn on: require a PR before merging, require the CI status check, require
   at least one approval (team mode only — a solo project sets it to 0, see
   [Solo mode](#solo-mode)), and disallow bypassing those rules for everyone (including admins, if
   the platform allows it). Check first that your plan offers it —
   [it may not](#when-branch-protection-isnt-available).

### When branch protection isn't available

Layer 3 depends on your plan. As of September 2026, GitHub offers branch protection — and rulesets,
its newer form — on **private** repositories only on paid plans (Pro for a personal account, Team
or Enterprise for an organization). On GitHub Free the API refuses with *"Upgrade to GitHub Pro or
make this repository public to enable this feature."* Public repositories get it on every plan.
Check your own host and plan rather than trusting this paragraph; plans change.

Without layer 3, nothing on the server enforces the PR, the green CI or the review. `main` is
guarded only by a hook each contributor must switch on and can skip with `--no-verify`, and by a
CI run that turns red but cannot stop a merge. That is a real gap, so choose one of these
deliberately:

1. **Upgrade the plan.** It's the only option that restores layer 3 for a private repo.
2. **Make the repository public**, if the code can be public.
3. **Stay private and hold the line by hand**, knowing it is weaker:
   - every contributor runs `bash install-hooks.sh`, because the hook is now the main barrier;
   - merge only through a PR, and never merge one whose CI is red. Add that sentence to the
     project's [AGENTS.md](../AGENTS.md) §3, so every AI session reads it as a rule;
   - treat any direct push to `main` as an incident, and record it in STATUS.md the same day.

Write the choice into PLAN.md's **Constraints** row, so nobody assumes a protection the repo
doesn't have.

## Solo mode

Everything above assumes someone other than the author reviews each PR. A one-person project has
nobody to do that, and the obvious setup fails: GitHub never lets you approve your own pull
request, and your AI copilots push as you. So "require one approval" plus "disallow bypass" blocks
every merge, forever.

A project with one human therefore runs in **solo mode** (recorded as the review mode in
[AGENTS.md](../AGENTS.md) §4). Branches, PRs, the gate, CI and branch protection all stay exactly
as they are. Only the reviewer changes:

- **The reviewer is a fresh AI, not the author.** Use the `code-reviewer` agent
  ([.claude/agents/code-reviewer.md](../.claude/agents/code-reviewer.md)), which starts with a
  clean context, or a different AI tool from the one that wrote the code. Never the session that
  wrote it: it shares every blind spot in its own work.
- **It reviews the whole branch** — `git diff main...HEAD` — against the lane's design doc and the
  Definition of Done ([AGENTS.md](../AGENTS.md) §8), placeholders included.
- **Its findings go on the PR as a comment**, "no issues found" included, so the review leaves the
  same record a human review would.
- **You read it, fix what needs fixing, and merge.** The AI reviews; the human still decides.

Branch protection in solo mode: require a PR, require the CI status check, **required approvals:
0**, disallow bypass. The PR and green CI stay mandatory; only the approval nobody could give is
dropped. (A private repo on GitHub Free can't have any of this — see
[When branch protection isn't available](#when-branch-protection-isnt-available).)

When a second person joins, switch to team mode: change the review mode in AGENTS.md §4 and raise
required approvals to 1.

## Commit messages

Small commits, clear messages, reference the task:
```
feat(parser): T007 add screenplay parsing service
fix(compliance): T029 correct rounding in ratio calc
docs: T035 confirm judging rubric
```

`<type>(<lane>): <TASK-ID> <summary>` — `<type>` is `feat`/`fix`/`docs`/`chore`; `<lane>` matches the
lane labels in [cross-ai-protocol.md](cross-ai-protocol.md); `<TASK-ID>` ties the commit back to
TASKS.md.

## Emergency bypass

Only when genuinely necessary (e.g. the hooks themselves are broken):
```bash
git push --no-verify
```
`--no-verify` skips the pre-push hook. Use sparingly, announce it in STATUS.md, and follow up
immediately to restore the gate — CI still checks the PR regardless.

## Secrets & artifacts

Never commit `.env`, credentials, uploaded user content, or generated artifacts — see `.gitignore`.


## Signing your commits

`git config user.name` is a claim, not proof — anyone can set it to yours. Signing makes authorship
verifiable, which matters more, not less, on a repo where several AI copilots commit alongside
several humans and the Log in STATUS.md is the record of who did what.

```bash
git config --global commit.gpgsign true      # or gpg.format=ssh to sign with your SSH key
```

Then add the public key to GitHub/GitLab so commits show as **Verified**. Background:
[security-basics.md](security-basics.md).

---

## The gate

Everything that decides "is this good enough to leave my machine" lives in **one** script,
[`scripts/gate.sh`](../scripts/gate.sh). The pre-push hook runs it. CI runs it. There is deliberately
no second copy, because two copies drift and then people learn to ignore the local one.

```
.githooks/pre-push ──┐
                     ├──> scripts/gate.sh ──> lint · types · tests · build · placeholders ·
                     │                        secrets · vulnerabilities · duplication
.github/workflows/ci ─┘
```

The hook itself only does the two things a hook alone can do: enforce branch policy, and work out
which commits are being pushed. It hands that file list to `gate.sh` and gets out of the way.

### The skip rule

> **A check that did not run is a failed check, not a passed one.**

This is the whole reason the gate is shaped this way. The kit used to say the opposite — "skip with a
visible message, never fail silently", with CI named as the backstop — and the result was a hook that
gated its Python suite behind `python -c "import pytest"`. On any Debian/Ubuntu-derived machine
`python` does not exist (only `python3`), so that check failed, the tests were skipped, and the hook
printed **"Test gate passed."** having run nothing at all. The named backstop did not exist either:
the kit referenced `.github/workflows/ci.yml` in three places and shipped no such file.

A skipped check and a passed check are indistinguishable to the person reading the output, so the
gate no longer has a "skip" state:

| Situation | Old behaviour | Now |
|---|---|---|
| Manifest present, no usable toolchain | skip, green | **fail** — name the manifest and the fix |
| `package.json`, no `node_modules` | skip, green | **fail** — dependencies aren't installed |
| `package.json`, no `test` script | `--if-present` → green | **fail** — nothing was proven |
| Python project, no `ruff` installed | skip lint, green | **fail** — lint and format couldn't run |
| `package.json`, no `lint` script | never linted, green | **fail** — nothing was analysed |
| Python project, no `pyright` installed | never type-checked | **fail** — the type check couldn't run |
| Project with no committed lockfile | never scanned | **fail** — no exact versions to check |
| `osv-scanner` missing, or can't reach OSV | never scanned | **fail** — the vulnerability scan didn't run |
| Source code, no `npx` for jscpd | never compared | **fail** — the duplication check didn't run |
| Manifests found, nothing ran | green | **fail** — that's a misconfiguration |
| Source pushed, no manifest anywhere | green | **fail** — the gate can't check it, so it won't claim to |
| No code in the repo at all | green | green, and says so explicitly |

The one deliberately soft case is `pytest` exit code 5, "no tests collected" — legitimate while a
package genuinely has no suite yet, so it reports loudly instead of failing, which stops it becoming
permanent quietly.

### Exemptions: declared and tracked, never silent

Occasionally a package genuinely has no suite and can't get one this week. The temptation is to give
it a fake `"test": "echo no tests"` script, which makes the gate green by making it lie — the exact
defect this whole design removes.

Instead, declare it against the task that will close it, using the same rule AGENTS.md §2a already
applies to stubs (*allowed only if the task explicitly declared it and a follow-up task ID exists*):

```bash
declare -A UNTESTED=(
  ["apps/web"]="T031"        # no test runner yet; T031 adds one
)
```

The difference from a fake test script is that this **does not go quiet**. Every run still prints
`apps/web has no test suite -- declared, tracked as T031`, and the entry only disappears when the
task closes. An exemption pointing at a task nobody wrote is the same failure as a stub nobody
tracked, so write the task first.

The same rule covers the two scans that look beyond the code in front of you:

- **A vulnerability with no fix yet** is declared in `osv-scanner.toml` at the repo root, with
  the task in its reason and an expiry date. The gate rejects an exemption that names no task, and
  prints every accepted one on every run
  ([security-basics.md](security-basics.md#dependencies-with-known-vulnerabilities)).
- **A deliberate copy** is marked in the code with `jscpd:ignore-start` / `jscpd:ignore-end` and
  the reason beside it ([code-analysis.md](code-analysis.md#duplication-across-the-repo)).

### Package managers

The package manager comes from the committed lockfile — `pnpm-lock.yaml` → `pnpm`, `yarn.lock` →
`yarn`, `bun.lockb` → `bun`, otherwise `npm`. Running `npm run build` in a pnpm workspace either
fails outright or silently resolves a different dependency tree than the one that was locked, so the
gate never assumes npm.

CI installs dependencies with `bash scripts/gate.sh --install-deps`, which walks the same
directories and picks the same package manager as the checks. It used to be a separate loop in the
workflow with its own list of directories, and the two drifted: a `frontend/` package was checked
by the gate but never installed by CI. The pre-push hook never installs anything — locally, a
missing install is yours to fix, and the gate says so.

### Changing the gate

Add checks to `scripts/gate.sh`, never to the workflow or the hook — anything added in only one place
is drift by construction. `bash scripts/gate.sh --list` prints what it would run here without running
it, which is the fastest way to see whether it has found your project layout at all. If it finds
nothing where you know there is code, teach `project_dirs()` about your layout rather than working
around it.

---

## Why branch-per-task, and not something else

The Curriculum's Git Workflows topic lays out the main branching strategies; this kit picks one on
purpose:

- **Branching by task/feature** ← what this kit uses. One branch per task in TASKS.md, short-lived,
  merged by PR. It fits a taskboard one-to-one, and it fits a team where an AI may own a lane for a
  few hours and then hand it over.
- **Branching for releases/environments** — a branch per environment (`dev`, `staging`, `prod`).
  Useful with a real release train; pure overhead on a project that deploys from `main`.
- **Git flow** — long-lived `develop` plus release and hotfix branches. Heavyweight; assumes versioned
  releases, which most projects here don't have.
- **Trunk-based** — everyone commits to `main` behind feature flags. Genuinely good, and genuinely
  demanding: it needs strong test coverage and flag discipline before it is safe. It is what this
  workflow grows into, not what it starts as.

### Rate of change, and why branches stay short

Conflicts are a function of two things: how much a branch diverges, and how long it stays diverged.
You control the second one. A branch alive for two days against a busy `main` will conflict; the same
work split across three branches merged the same day usually won't.

- Keep a branch to **one task**. If a task is too big to finish in a sitting, it's too big — split it
  (see the task anatomy at the top of [TASKS.md](../TASKS.md)).
- `git switch main && git pull` before branching, and rebase onto fresh `main` if your branch has
  been open a while.
- Two lanes editing the same files is a coordination failure, not a git problem — claim lanes in
  STATUS.md first ([cross-ai-protocol.md](cross-ai-protocol.md)).

### Resolving conflicts

Read both sides before touching anything. A conflict means two people had a reason; deleting theirs
because yours compiles loses the reason. When the conflict is in a file the design doc describes, the
design doc decides — and if neither side matches it, both are wrong. Re-run `bash scripts/gate.sh`
after resolving: a mechanical merge that satisfies git can still be nonsense.
