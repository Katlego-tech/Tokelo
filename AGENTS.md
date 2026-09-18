# AGENTS.md — the Tokelo contract

This is the single contract every contributor follows — **human or AI, whichever tool**.
Read it before you touch anything. If a rule here conflicts with a habit, the rule wins.

Entry points funnel here: every per-tool file (e.g. [CLAUDE.md](CLAUDE.md), [GEMINI.md](GEMINI.md))
says "read AGENTS.md first." This file is the source of truth for *how we work*; the
**Non-negotiables** in [PLAN.md](PLAN.md) are the source of truth for *what cannot be compromised*.

> **New session / new tab / new AI? Do this before anything else:**
> 1. Read **[STATUS.md](STATUS.md)** — the live board: what's done, in progress, and next.
> 2. Read this file — the rules below.
> 3. Check the **lane labels** so you don't collide with someone else's work.
> 4. When you finish a meaningful step, **update STATUS.md** before you stop.

---

## 1. Team & lanes

| Person | Role | AI copilot(s) |
|--------|------|----------------|
| Katlego | Project leader | Claude |

> 📝 **Customize:** add a row per contributor. Solo project? One row, and "lanes" still matter — they're
> how *you* avoid two of your own AI sessions colliding. Set the review mode in §4 to `solo` as well.

We do **not** hard-partition file ownership by person; we coordinate with **lane labels** in
[STATUS.md](STATUS.md) instead (e.g. `<lane-example-1>`, `<lane-example-2>`, `docs`, `infra`). Before
working a lane, claim it in the STATUS.md "Current focus" table so nobody else — human or AI — collides
with it.

**Rule:** never edit a file another active lane owns without saying so in STATUS.md first.

### Frontend work goes to Claude

Lanes are otherwise first-come — with one standing exception. **Any lane that produces
user-facing UI is assigned to Claude by default**: visual design, component structure,
styling and token systems, layout, accessibility, and interaction.

Why this one is pinned rather than claimed: the `frontend-design` skill in `.claude/skills/`
only loads for Claude, and it is the thing that keeps UI from drifting into the templated
look. A project's visual identity also degrades fastest when it is authored by several hands
in turn — palette and spacing decisions get re-litigated per session, and the result reads as
assembled rather than designed. One owner keeps it coherent.

In practice:

- Frontend lanes (`feat/<ui-lane>`) are Claude's unless the STATUS.md focus table says otherwise.
- Other AIs may still **use** existing components and read the token file; what they should not
  do is introduce a new palette, restyle a component, or hand-roll UI that bypasses the
  component layer.
- If another AI needs UI to finish its own lane, it wires up the existing components and notes
  in STATUS.md that the styling needs a Claude pass — rather than inventing a look in passing.
- Backend, data, infra and docs lanes carry no such default; claim whichever is free.

If the project has no frontend, this section is inert — delete it.

## 2. How we plan

Planning is driven directly by the team through living documents:

- [SPEC.md](SPEC.md) — the WHAT (user stories, acceptance criteria).
- [PLAN.md](PLAN.md) — the HOW (stack, non-negotiables, code layout, build phases).
- [docs/design/](docs/design/) — the SHAPES (class / sequence / state diagrams, per lane).
- [TASKS.md](TASKS.md) — the checkbox task list (`T001…`).
- [STATUS.md](STATUS.md) — the live board.

The full loop is in [docs/planning-workflow.md](docs/planning-workflow.md).

- **Shared state lives in exactly three places:** AGENTS.md (rules), STATUS.md (live board),
  TASKS.md (the task list). Everything else is derived. If it isn't reflected in these three, it
  didn't happen.
- **Single writer per task.** One task ID (`T0xx`) is worked by one person/AI at a time. Claim it in
  STATUS.md before you start; release it when the PR merges.

See [docs/cross-ai-protocol.md](docs/cross-ai-protocol.md) for the collision-avoidance detail.

## 2a. Build to a drawn shape, and never ship a placeholder

Two rules that apply to every contributor, and that exist because of one specific, repeated failure:
work comes back **adjacent to** what was asked — *a* screen instead of *the* screen, the agreed
function names with stubbed bodies, the right entity with invented fields — and gets reported as
done, because by the letter of the task it was.

**Before you build:**

- Non-trivial work has a **design doc** in [docs/design/](docs/design/) — class diagram for
  entities, sequence diagram for anything crossing a service or agent boundary, state machine for
  anything with a lifecycle, and the exact contracts between lanes. Written in Mermaid, merged
  before the implementation tasks are. Rules and the which-diagram-when table:
  [docs/design-documentation.md](docs/design-documentation.md).
- **If the task has no design reference and you can't tell exactly what shape to build, stop and
  say so.** Write the design doc (it's markdown; it takes minutes) or ask. Do not proceed on a
  plausible interpretation — a plausible-but-wrong implementation is the expensive outcome here,
  because it looks finished.
- **UI work builds to a named visual reference** — the mockup path, the screenshot, the screen it
  must match. If none exists, producing one is the first task, not an assumption you make quietly.

**When you finish:**

- **No placeholder counts as done.** Not `TODO`, not `FIXME`, not `pass` / `NotImplementedError`,
  not an empty component, not hard-coded sample data standing in for a real call, not a function
  returning a constant to make a test green. If the real thing can't be built yet, the task is
  **blocked** — say so in STATUS.md and name what unblocks it. Reporting a stub as complete is a
  correctness failure, not a shortcut.
- The only exception: a stub the task text **explicitly declared**, with a follow-up task ID
  already written for replacing it.
- **Implementation is checked against the diagram**, not the prose. Every class in the design
  exists with those fields; the call order matches the sequence; every drawn state is reachable and
  every undrawn transition is impossible. Code and diagram disagree → fix whichever is wrong, in
  the same PR.

## 3. `main` is always green

- **Branch-only.** Nobody pushes to `main`, ever. The pre-push hook rejects it.
- Enable the hooks once per clone — every contributor, on every clone, because `core.hooksPath` is
  local config and is never cloned: `bash install-hooks.sh`.
- One gate, two triggers: [`scripts/gate.sh`](scripts/gate.sh) holds every check, the
  [pre-push hook](.githooks/pre-push) runs it locally, and [CI](.github/workflows/ci.yml) runs the
  same script on every PR. Add checks to `gate.sh` only — anything added in one place drifts.
- **A check that did not run is a failed check.** The gate has no skip state: missing tooling,
  uninstalled dependencies, or a package with no test script all fail the push rather than reporting
  green. Rationale: [docs/git-workflow.md](docs/git-workflow.md#the-skip-rule).
- A red `main` blocks the whole team, so it never happens.

## 4. Branch & commit flow

- Branch names: `feat/<lane>`, `fix/<thing>`, `docs/<thing>`, `chore/<thing>`.
- Open a PR into `main`. The gate must be green. Then it is reviewed, according to this project's
  **review mode**:
  - **Team mode** (two or more people): a quick review from another contributor.
  - **Solo mode** (one person): a review by a fresh AI reviewer — the `code-reviewer` agent, or a
    different AI tool from the one that wrote the code, never the same session — posted on the
    PR and read by you before you merge. GitHub never lets you approve your own PR, so this
    replaces the human approval; it does not skip review. Details:
    [docs/git-workflow.md](docs/git-workflow.md#solo-mode).

  This project's review mode: **`solo`**
- Commit format ties work back to a task ID: `type(lane): T0xx short description`
  (e.g. `feat(audio): T012 faster-whisper HIP transcription`).

Full detail: [docs/git-workflow.md](docs/git-workflow.md).

## 5. Update STATUS.md every step

After any meaningful step, update [STATUS.md](STATUS.md):
1. Tick / add the relevant checkbox and task ID (in [TASKS.md](TASKS.md)).
2. Update the lane's **Status** column and the phase timeline.
3. Add a dated line to the **Log** at the bottom.

Format the header line as: `_Last updated: YYYY-MM-DD — by <name> (via <tool>)_`.

If you don't update STATUS.md, the next session (human or AI) starts blind and you get conflicts.
**Treat STATUS.md as part of "done."**

## 6. Grounding & honesty rules

> 📝 **Customize this section entirely** — it's the single highest-leverage section in this file. Every
> real project has *some* thing an AI must never fabricate (data, citations, financial figures, legal
> claims, screenplay facts, medical claims...). Name yours explicitly; a vague "be accurate" doesn't work
> as a rule anyone can check a PR against. Examples that shipped elsewhere:
> - *"Caption only what the evidence supports — no invented people, places, dialogue, or events."*
> - *"Every extracted entity MUST be verifiable in the source document — no hallucinated production data."*

- **`Never state, cite or paraphrase a statute, section, time limit or case that isn't in Tokelo's curated legal sources (Rental Housing Act 50 of 1999; Consumer Protection Act 68 of 2008, sections 14 and 48; PIE Act 19 of 1998), and never present legal information as legal advice.`.** This is **Non-negotiable I** in [PLAN.md](PLAN.md).
- **Respect the budgets.** `<runtime/latency/cost/size budgets, if any>`.
- **Deterministic I/O / graceful degradation.** `<what a partial failure must still produce>`.
- **Report failures honestly.** If a stage breaks or a result comes out weak, say so in STATUS.md.
  Don't paper over a broken run.

## 7. Repository map

```
Tokelo/
├── README.md · AGENTS.md · <per-tool>.md         shared-state entry points
├── STATUS.md · STATUS.template.md                the live board + its template
├── SPEC.md · PLAN.md · TASKS.md                  the planning documents
├── DESIGN-DOC.template.md                        the per-lane design-doc template
├── docs/                                         topic docs (incl. architecture-defaults.md)
│   └── design/                                   per-lane design docs — the diagrams code is built to
├── .claude/                                      agents, /feature-dev command, frontend-design skill
├── scripts/gate.sh                               THE gate — every check lives here, and only here
├── .githooks/pre-push                            branch protection; runs scripts/gate.sh
├── .github/workflows/ci.yml                      runs the same scripts/gate.sh
├── install-hooks.sh                              run once per clone, by everyone
└── <your services/apps tree + docker-compose>    see docs/project-structure.md
```

Our default build shape (microservices · Kafka/RabbitMQ · shadcn/ui · Docker · latest-LTS-pinned)
lives in [docs/architecture-defaults.md](docs/architecture-defaults.md) — with per-project deviations
recorded in [PLAN.md](PLAN.md)'s Technical Context.

## 8. Definition of Done

A task is done when **all** of these hold:
- [ ] Code + tests written; tests were written **first**, failed for the right reason, and now pass.
- [ ] **It matches its design doc** — every class/field, every call in the sequence, every state
      (§2a). Doc corrected in the same PR if reality diverged.
- [ ] **No placeholders anywhere in the diff** — no `TODO`/`FIXME`, stub body, empty component,
      hard-coded stand-in data, or constant-returning function, except one the task explicitly
      declared *and* that has a follow-up task ID (§2a).
- [ ] For UI: visually matches the reference named in the task, not merely "a version of" it.
- [ ] **`bash scripts/gate.sh` is green — and green because it ran, not because it found nothing.**
      Check the count it prints; lint, format, types, and tests all actually executed.
- [ ] The app still boots/imports; the golden-path example still works.
- [ ] No secret in the diff (the gate sweeps, but it only catches known shapes —
      [docs/security-basics.md](docs/security-basics.md)).
- [ ] No dependency with a known vulnerability, unless it's declared in `osv-scanner.toml` against
      a task; no copied logic pushing duplication over the threshold (the gate checks both).
- [ ] Runs inside any stated budgets (no new regression in latency/memory/cost).
- [ ] STATUS.md updated (checkbox + lane status + Log line); task ID referenced in the commit.
- [ ] PR opened into `main`, CI green, reviewed according to the review mode in §4, merged.

---

## Secret Realm rules

This is a Secret Realm project: `realm.toml` names its tier and platform. Everything above still
holds; these are added, and the gate or the release pipeline checks each one.

1. **Work traces to requirements.** Every task carries `Req:` (or `Req: none — <why>`), every
   test of an approved requirement names it, and every commit names its task. `realm trace`
   refuses a broken chain. Requirements live in REQUIREMENTS.md, each with its level, state and
   verification method.
2. **Decisions are ADRs, and they're frozen.** A decision the build rests on gets
   `docs/adr/NNNN-title.md`. Once it's accepted, never edit its text: write a new ADR that
   supersedes it. `realm adr-check` fails on an edit or a deletion.
3. **Every design works out its threats.** Each design doc in `docs/design/` ends with its STRIDE
   threats, each with a mitigation, or "None, because <reason>". The C4 diagrams in
   `docs/architecture/` stay true to the code.
4. **Releases go through the pipeline, never by hand.** Tag, stage, UAT sign-off, promote
   (`docs/release/README.md`). Never skip or loosen a release check to get a release out; a
   check that can't run fails. To undo a release: `bash scripts/realm/release.sh rollback <version>`.
5. **The error budget rules feature work.** When a service's budget in `docs/ops/slo.toml` is
   spent, stop feature work on it: the next tasks are corrective (`fix`) or preventive (`test`,
   `chore(harden)`) until it recovers.
6. **Incidents end in a change.** Close an incident only with its blameless postmortem and the
   commit or PR that stops it happening again. `realm incidents` checks this.
7. **Upkeep names T000.** Dependency updates, runtime upgrades and the weekly gate's findings
   name T000, the standing maintenance task.
