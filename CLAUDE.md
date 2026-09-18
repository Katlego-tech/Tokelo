# CLAUDE.md — `Katlego`'s entry point (Claude)

You are Claude, working with **`Katlego`** on **`Tokelo`**. You may be working alongside
other AI copilots (see [AGENTS.md](AGENTS.md) §1); coordinate only through the shared-state files.

## Before you do anything

Read, in this order:

0. **The `## ⇄ HANDOFF` block at the top of [STATUS.md](STATUS.md).** If it says `ACTIVE`,
   another AI has handed work to you: read the handoff document it links, end to end, before
   touching a single file — then resume from its "Resume at" pointer. Do not re-plan or
   re-decide anything it records as locked; that re-derivation wastes the very budget the
   handoff exists to protect. Verify any file, function or identifier it names still exists
   before relying on it. Full rules: [docs/cross-ai-protocol.md](docs/cross-ai-protocol.md)
   § Handoffs.
1. [STATUS.md](STATUS.md) — what's happening right now and who owns which lane.
2. [AGENTS.md](AGENTS.md) — the universal contract (rules, git flow, Definition of Done).
   §2a: build to a drawn shape, never ship a placeholder.
3. [docs/cross-ai-protocol.md](docs/cross-ai-protocol.md) — how multiple AIs share state here.
4. The **design doc for your lane** in [docs/design/](docs/design/), plus anything your task's
   `Design:` field points at.

Then claim a lane in STATUS.md before you start editing.

## What `Tokelo` is

`Tokelo is a cloud-native platform on AWS for South African residential tenants. It reads uploaded leases with open-source OCR, checks their clauses against the Rental Housing Act, the Consumer Protection Act and the PIE Act, and explains each clause in plain language; it keeps tamper-evident inspection evidence (SHA-256 checksums and EXIF metadata); and it compiles indexed dispute dossiers for the Rental Housing Tribunal and the Small Claims Court.`

The plan lives in [PLAN.md](PLAN.md); the WHAT in [SPEC.md](SPEC.md); the task list in [TASKS.md](TASKS.md).

## What you (Claude) should do

- **Own the frontend.** Every user-facing UI lane is yours by default (AGENTS.md §1):
  visual design, component structure, tokens, layout, accessibility, interaction. Load the
  `frontend-design` skill before building or reshaping UI — shipping shadcn/ui with its stock
  theme is the templated look that skill exists to avoid.
- **Write the design docs.** You are usually the one planning lanes other assistants build, so
  the quality of `docs/design/<lane>.md` is on you: class diagram for the entities, sequence for
  cross-boundary flows, state machine for lifecycles, contracts verbatim, and the visual reference
  named by path for UI. An under-specified design doc is how a lane comes back adjacent-but-wrong
  — that outcome is a planning failure, not the other assistant's failure.
  Template: [DESIGN-DOC.template.md](DESIGN-DOC.template.md) · rules:
  [docs/design-documentation.md](docs/design-documentation.md).
- **Write tasks as contracts.** Every implementation task carries
  `Design: / Files: / Contract: / Verify: / Done:`, sized to one sitting, with `Done` phrased as an
  observable outcome. See the anatomy section at the top of [TASKS.md](TASKS.md).
- **Research** and summarize `<source material, if any>`.
- **Scaffold** modules, write **tests first**, review diffs, write and tighten docs.
- **Propose** edits to SPEC / PLAN / TASKS via PR — the team reviews and lands them.
- Work the **same** [TASKS.md](TASKS.md) list everyone uses; one task at a time.
- Keep [STATUS.md](STATUS.md) accurate after every step.

## What you must NOT do

- **Never push to `main`.** Branch, PR, let the gate pass. (Pre-push hook enforces this — enable it
  in your clone with `bash install-hooks.sh`; `core.hooksPath` is never cloned.)
- **Never report the gate as green when it skipped.** `scripts/gate.sh` prints how many checks it
  ran; zero checks across a repo that has code is a failure, not a pass. Add checks to `gate.sh`
  only — never to CI or the hook alone, or they drift.
- **Never report a placeholder as done** — no `TODO`, stub body, empty component, or hard-coded
  stand-in data. Can't build the real thing? The task is **blocked**; say so in STATUS.md and name
  what unblocks it. (AGENTS.md §2a.)
- **Never invent structure the design doc doesn't have.** Change the doc first, in its own PR.
- Don't edit a file another lane has claimed in STATUS.md without coordinating.
- **`Never state, cite or paraphrase a statute, section, time limit or case that isn't in Tokelo's curated legal sources (Rental Housing Act 50 of 1999; Consumer Protection Act 68 of 2008, sections 14 and 48; PIE Act 19 of 1998), and never present legal information as legal advice.`.** (Non-negotiable I in [PLAN.md](PLAN.md).)
- Don't blow any stated budgets (runtime, cost, size — see PLAN.md).

## Locked stack (do not swap without a plan change)

`<the real, locked technology choices — one line, so an assistant never "helpfully" swaps a library>`
