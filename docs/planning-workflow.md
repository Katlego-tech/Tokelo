# Planning workflow

`Tokelo` is planned with plain, self-driven documents — no external orchestrator required.
Four living documents plus a folder of design docs are all you need.

> 📝 **Customize:** this describes the lightweight path (what OmniCaption used, after actively
> *removing* a heavier tool mid-project). If your project instead drives builds through a formal
> spec-lifecycle tool (e.g. GitHub's Spec-Kit / `specify` CLI, run via an AI like IBM Bob), see
> **"The heavier alternative"** below — the two are not meant to run at once.

## The planning documents

| Document | Role | Analogue |
|----------|------|----------|
| [SPEC.md](../SPEC.md) | **The WHAT** — user stories, acceptance criteria, scoring. | the requirements |
| [PLAN.md](../PLAN.md) | **The HOW** — stack, non-negotiables, code layout, build phases, test gate. | the design |
| [docs/design/](design/) | **The shapes** — per-lane design docs: class, sequence, state diagrams. | the blueprints |
| [TASKS.md](../TASKS.md) | **The task list** — dependency-ordered `T001…`, checkbox per task. | the backlog |
| [STATUS.md](../STATUS.md) | **The live board** — who owns what right now, timeline, log. | the standup |

## The loop

1. **Agree the WHAT.** Edit [SPEC.md](../SPEC.md) — user stories + acceptance criteria. Keep it
   implementation-agnostic.
2. **Design the HOW.** Edit [PLAN.md](../PLAN.md) — stack, module layout, phases. Check it against
   the **non-negotiables** listed there before building.
3. **Draw the shapes.** For every non-trivial lane, write `docs/design/<lane>.md` from
   [DESIGN-DOC.template.md](../DESIGN-DOC.template.md) — class diagram for the entities, sequence
   diagram for the cross-service flow, state machine for anything with a lifecycle, and the exact
   contracts between lanes. Merge these *before* the implementation tasks are written. Rules and
   the which-diagram-when table: [design-documentation.md](design-documentation.md).
4. **Break it down.** Edit [TASKS.md](../TASKS.md) — one checkbox task per unit of work, each
   carrying its `Design:` / `Files:` / `Contract:` / `Verify:` / `Done:` fields, tagged with its
   user story, and marked `[P]` if parallelizable. See the task anatomy and the no-placeholder
   rules at the top of [TASKS.md](../TASKS.md).
5. **Claim & build.** Claim a task/lane in [STATUS.md](../STATUS.md), branch, write the test first,
   implement **to the diagram**, open a PR. One writer per task.
6. **Land & update.** Merge via a green PR, tick the task in TASKS.md, update STATUS.md. If the
   code and the design doc ended up disagreeing, fix the doc in the same PR.

Steps 3 and 4 are the ones that get skipped under time pressure, and they are the two that decide
whether what comes back is the thing you asked for. See below.

## Why planning is this heavy

The failure this workflow is built around is not an assistant that *can't* build the thing. It's an
assistant that builds **something adjacent to** the thing — a UI that is *a* screen rather than
*the* screen, a service with the agreed names and stubbed bodies, a model with the right noun and
the wrong fields — and reports it as done, because by the letter of the task it was.

That happens for one reason: **the task carried the words but not the structure.** Natural language
under-determines shape. Every gap an implementer finds gets filled with something plausible, and
plausible-but-wrong is expensive precisely because it looks finished.

So the two cheap countermeasures, applied before any code:

- **Draw it** (step 3). A class diagram cannot be satisfied by a class with different fields; a
  sequence diagram cannot be satisfied by calls in a different order. Diagrams are checkable in a
  way that paragraphs are not — and Mermaid is text, so every assistant can read *and* write it.
- **Specify the task as a contract** (step 4). `Design / Files / Contract / Verify / Done` on every
  implementation task. `Done` is phrased as an outcome, so "the file exists" can never pass for
  "it works", and a task can never be closed on a `TODO`.

Both are markdown, both land in minutes, and both are dramatically cheaper than discovering after
the fact that a lane was built to the wrong shape.

## Planning for a specific assistant

The docs are tool-agnostic on purpose — but *which* structural gaps get filled with a guess does
vary by assistant, and a lane that came back wrong is data. When one does:

1. Don't just fix the code. Ask **which gap in the task or design doc let it be wrong**, and close
   that gap in the document.
2. If a whole class of mistake recurs (inventing fields, skipping the reference mockup, stubbing
   the hard call), add it as an explicit prohibition in that assistant's entry-point file and, if
   it generalises, in [../AGENTS.md](../AGENTS.md).
3. Note the correction in STATUS.md's Log, so the next session doesn't relearn it.

This is the mechanism by which the process actually improves: **every wrong output becomes a
sharper document, not just a fixed file.**

## Who ratifies changes

There is no automated "system of record." Changes to SPEC/PLAN/TASKS land like any other change —
via a PR, reviewed according to the review mode in [AGENTS.md](../AGENTS.md) §4.
`<the project leader / decision-maker>` has the final call
on scope and the non-negotiables; everyone keeps the documents current.

---

## The heavier alternative: a formal Spec-Kit lifecycle

If the project is built with an AI whose whole workflow is spec-driven (e.g. `/speckit.constitution →
/speckit.specify → /speckit.clarify → /speckit.plan → /speckit.tasks → /speckit.implement`), let that
tool own the generated artifacts and treat SPEC.md/PLAN.md/TASKS.md in this kit as the **human-written
seed** you feed into it:

- `constitution` ← your **non-negotiables** (PLAN.md)
- `specify` ← [SPEC.template.md](../SPEC.template.md)
- `plan` ← [PLAN.template.md](../PLAN.template.md)
- `tasks` ← [TASKS.template.md](../TASKS.template.md)

The design docs are **not** replaced by a spec tool's generated artifacts — `docs/design/` stays,
and `plan` is fed from it. A generated plan describes intent; the class and sequence diagrams are
what implementation is checked against ([design-documentation.md](design-documentation.md)).

The generated versions (typically under a `specs/` directory) become the system of record for
implementation; **STATUS.md and AGENTS.md stay the coordination layer regardless** — every AI still
reads them first and updates them last (see [cross-ai-protocol.md](cross-ai-protocol.md)). Only one
assistant should own the `implement` step; parallel assistants work research, scaffolding, tests, and
docs around it, never the same task simultaneously.

**Switching from heavy to light mid-project is fine** — fold the constitution's substance into PLAN.md's
Non-negotiables, delete the spec-tool's generated tree, and go back to editing SPEC/PLAN/TASKS
directly. Document the switch in STATUS.md's Log so nobody wonders where the old artifacts went.
