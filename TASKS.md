# `Tokelo` — Tasks

**Plan:** [PLAN.md](PLAN.md) · **Spec:** [SPEC.md](SPEC.md) · **Designs:** [docs/design/](docs/design/)

> One of the three shared-state files (with [AGENTS.md](AGENTS.md) and [STATUS.md](STATUS.md)).
> **One writer per task** — claim it in STATUS.md before you start.

---

## How tasks are written here

A task is a **contract**, not a reminder. The person writing it and the person (or AI) building it
are usually not the same, and the builder will implement *exactly* what the task specifies — so a
task that under-specifies gets you something plausible-looking and wrong: the right file with a
`TODO` in it, a component that renders *a* screen rather than *the* screen, a function with the
agreed name and a stubbed body.

**The task is under-specified if a competent implementer who read nothing else could build
something structurally different from what you intend.** When that's true, the fix is not a longer
sentence — it's a design doc ([docs/design-documentation.md](docs/design-documentation.md)) and a
reference to it.

### Anatomy

```
- [ ] T0nn [P] [US1] <imperative one-line summary>
      Design:  docs/design/<lane>.md §<section>        <- the structure to build to
      Files:   <paths this task creates or changes>
      Contract:<exact signature / schema / props — or the design §ref that has it>
      Verify:  <the command or check that proves it works>
      Done:    <the observable end state, in the user's or caller's terms>
```

| Field | Required when | Why it's there |
| --- | --- | --- |
| **Design** | the task creates structure (types, services, screens, flows) | gives the implementer a diagram to build to instead of a guess |
| **Files** | always, unless genuinely unknowable | stops two lanes colliding; makes "did it touch the right thing" reviewable |
| **Contract** | anything another lane or task consumes | lets parallel lanes compose instead of each inventing an interface |
| **Verify** | always | a task with no check is a task nobody can close honestly |
| **Done** | always | phrased as an outcome, so "the file exists" can't pass for "it works" |

### Rules

1. **No placeholder deliverables.** A task may not be closed with `TODO`, `FIXME`, `pass`,
   `NotImplementedError`, an empty component, hard-coded fake data standing in for a real call, or
   a function that returns a constant to make a test green. If the real thing can't be built yet,
   the task is **blocked**, not done — say so in STATUS.md and name what unblocks it.
   *The one exception:* a deliberately stubbed dependency that the task text names as a stub, with
   a follow-up task ID already written for replacing it.
2. **Every task is a vertical slice.** "Create the module skeleton" is not a task; "parse a
   pain.001 payload into a `Transfer` and reject a malformed one" is. Scaffolding is part of the
   first behavioural task, not a task of its own.
3. **Sized to one sitting.** If a task can't be finished and verified in one working session,
   split it. Long tasks are where placeholders come from — the implementer runs out of room and
   leaves a marker.
4. **Tests first, and the test must fail for the right reason.** A test that passes against an
   empty implementation is not a test. Write it, watch it fail, then implement.
5. **UI tasks name their visual reference by path.** Never "build the dashboard" — always "build
   the dashboard in `<path>/screen.png`, matching layout, tokens and copy". See
   [docs/design-documentation.md](docs/design-documentation.md) § UI is a special case.
6. **One story label per task.** If a task serves two user stories, it's two tasks.
7. **`[P]` means genuinely parallel** — disjoint files *and* no unmet dependency. If two `[P]`
   siblings both touch the same file, one of them is mislabelled.

### Good vs. bad

> ❌ `- [ ] T014 [US2] Build the compliance dashboard`
>
> Produces: *a* dashboard. Some cards, some invented metrics, a chart library nobody chose.
>
> ✅
> ```
> - [ ] T014 [US2] Build the Compliance Health Dashboard screen
>       Design:  docs/design/compliance-ui.md §3 (component tree), §2 (reference)
>       Files:   apps/web/src/pages/ComplianceDashboard.tsx, apps/web/src/components/compliance/*
>       Contract:consumes GET /api/compliance/health -> ComplianceHealth (docs/design/compliance-ui.md §6)
>       Verify:  npm test -w apps/web && npm run dev, compare against legacy/mockups/compliance/screen.png
>       Done:    all six modules from the mockup render with live data from the endpoint; no
>                hard-coded metric values remain in the component
> ```

---

## Legend

Format: `[ID] [P?] [Story] Description`

- **[ID]** — task identifier `Tnnn`, monotonically increasing, never reused.
- **[P]** — parallelizable: touches different files from its siblings and has no unmet dependency.
- **[Story]** — the label the task serves (`US1`–`USn`, `SET` setup, `FND` foundational,
  `DSN` design/documentation, `POL` polish).
- Commit format: `feat(scope): Tnnn short description` (e.g. `feat(audio): T041 add HIP whisper loader`).

Each user-story phase is ordered **Design → Tests FIRST (must FAIL) → Implementation → Checkpoint**.

---

## Phase 0 — Design

> Merged before Phase 2 implementation starts. Cheap, markdown-only, and the thing that decides
> whether everything after it is built to a shape or to a guess.

- [ ] T001 [DSN] `<docs/design/domain-model.md — class diagram for the core entities>`
      Req:     none — design documentation
- [ ] T002 [P] [DSN] `<docs/design/<lane>.md — one design doc per non-trivial lane>`
      Req:     none — design documentation

**Checkpoint:** every lane in Phase 2+ has a merged design doc; `docs/design/README.md` indexes them.

---

## Phase 1 — Setup

- [ ] T0xx [SET] `<repo skeleton>`
- [ ] T0xx [P] [SET] `<lint/test config>`
- [ ] T0xx [P] [SET] `<CI workflow>`
- [ ] T0xx [SET] `<.githooks/pre-push + git config core.hooksPath .githooks>`
- [ ] T0xx [SET] `<seed STATUS.md, AGENTS.md — the shared-state protocol>`

**Checkpoint:** repo builds/boots, lint + an empty test run pass, CI is green.

---

## Phase 2 — Foundational (blocking)

- [ ] T0xx [FND] `<the thing every user story depends on>`
      Design:  `<docs/design/...>`
      Files:   `<...>`
      Contract:`<...>`
      Verify:  `<...>`
      Done:    `<...>`

**Checkpoint:** `<the thin end-to-end spine works, even if it does nothing useful yet>`

---

## Phase 3 — US1 `<title>`

- [ ] T0xx [US1] Write failing test for `<behavior>`.
      Verify:  `<test command>` — fails with `<the specific expected failure>`
      Done:    test exists, runs, and fails because the behaviour is absent (not because it errors)
- [ ] T0xx [US1] Implement `<behavior>` until the test passes.
      Design:  `<docs/design/... §n>`
      Files:   `<...>`
      Contract:`<...>`
      Verify:  `<test command>` — green
      Done:    `<observable outcome; no stubs, no hard-coded returns>`

**Checkpoint:** US1 is independently demoable.

---

<!-- Repeat the US-phase pattern for each user story in SPEC.md, then close with Polish. -->

## Phase N — Polish

- [ ] T0xx [POL] `<docs, checklist, release>`
- [ ] T0xx [POL] Sweep for placeholders: no `TODO`/`FIXME`/stub bodies/hard-coded sample data
      remain outside of tasks that explicitly declared them, and each declared one has an open
      follow-up task ID.

---

## Secret Realm: every task traces to a requirement

Every task also carries a **Req:** field, next to Design, Files, Contract, Verify and Done:

```
      Req:     REQ-012, NFR-003          the requirements it serves
      Req:     none — <why>              tooling, refactoring or docs: say which
```

`scripts/realm/realm trace` (part of the gate) refuses a task without one, a commit that names no
task, and an approved requirement that no task or test names.

## Standing tasks

- [ ] T000 [MNT] Keep the project maintained: dependency updates, runtime upgrades, and the weekly gate's findings
      Req:     none — preventive and adaptive maintenance (ISO/IEC 14764)
      Verify:  the weekly realm-scheduled run is green
      Done:    never: it stays open for the life of the project
