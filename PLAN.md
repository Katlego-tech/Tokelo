# `Tokelo` — Implementation Plan (the HOW)

**Companions:** [SPEC.md](SPEC.md) (the WHAT) · [docs/design/](docs/design/) (the shapes) ·
[TASKS.md](TASKS.md) (the task list)

---

## Summary

`<One paragraph: the shape of the solution — architecture in one breath, the key technical bet, and
the hard constraints it has to live inside (budgets, deadline, compliance).>`

---

## Non-negotiables (project principles)

These are the values every change is held to. If you're also running Spec-Kit or a similar tool,
this list is the "constitution" in plain language — keep both in sync, or drop the formal
constitution and let this section be the single copy (see
[docs/planning-workflow.md](docs/planning-workflow.md)).

> 📝 **Customize:** every project needs its own list, but these categories are close to universal —
> fill in the real content, don't leave the placeholder text.

1. **`<Grounding/quality rule>`** — say only what the evidence/spec supports.
2. **`<Hard budget rule>`** — runtime, memory, cost, or size ceilings, if any.
3. **Test-first.** Each user story writes failing tests before implementation.
4. **Design before code, and no placeholders.** Non-trivial lanes have a merged design doc in
   [docs/design/](docs/design/) with the diagrams implementation is checked against; nothing ships
   with a `TODO`, a stub body, or hard-coded stand-in data. Can't build the real thing → the task
   is blocked, not done. (AGENTS.md §2a ·
   [docs/design-documentation.md](docs/design-documentation.md).)
5. **Phased delivery.** Independent user stories; each phase ends demoable.
6. **Coordinate through shared state.** STATUS.md, AGENTS.md, and TASKS.md are the only coordination
   surfaces; one writer per task.
7. **Branch-only, always-green `main`.** No direct pushes; every change lands via PR with a green gate.

---

## Technical Context

> 📝 The Architecture / Messaging / Frontend / Containerization rows carry this project's defaults
> from [docs/architecture-defaults.md](docs/architecture-defaults.md) — overwrite them if this
> project has a real reason to deviate (and say what it is), don't just leave them as unexamined
> defaults. Record **exact, pinned versions** in the `Language(s)` / `Runtime` rows — default is the
> latest LTS/stable, verified against the source rather than assumed (architecture-defaults §5).

| Dimension | Value |
| --- | --- |
| **Language(s) + versions** | `<e.g. Python 3.12 (LTS), Node 22 LTS — pinned>` |
| **Architecture** | `Event-driven: a Python API on ECS Fargate, with async workers (Lambda or ECS) fed by SQS; split services only where a module needs it` |
| **Messaging / async** | `Amazon SQS (FIFO, with dead-letter queues), fed by EventBridge` |
| **Frontend** | `React + shadcn/ui (Radix + Tailwind + CVA)` |
| **Containerization** | `Docker per service + one docker-compose.yml for local dev` |
| **Runtime/deploy target** | `<>` |
| **Data layer** | `<>` |
| **Key external services/models** | `<>` |
| **Testing** | `<framework(s), lint + type-check tools>` |
| **Perf/cost goals** | `<>` |
| **Constraints** | `<>` |
| **Scale** | `<expected load/volume>` |

---

## Project structure (as scaffolded)

`<Paste the real tree once it exists — see docs/project-structure.md for the full write-up. Keep
this section as the short version linked from PLAN.md; the long version lives in docs/.>`

```
<repo>/
└── ...
```

---

## Design documents

The diagrams implementation is built and reviewed against. One per non-trivial lane, merged before
that lane's implementation tasks are written — see
[docs/design-documentation.md](docs/design-documentation.md).

| Lane | Design doc | Covers |
| --- | --- | --- |
| `<lane>` | [docs/design/`<lane>`.md](docs/design/) | `<class / sequence / state / contracts>` |

---

## Build phases (MVP-first)

Mirrors [TASKS.md](TASKS.md). Each phase should be independently demoable at its checkpoint.

0. **Design** — domain model + one design doc per non-trivial lane (markdown, merged first).
1. **Setup** — repo skeleton, CI, lint/test config, schemas/contracts.
2. **Foundational (blocking)** — the pieces every user story depends on.
3. **US1** — `<first user story, thinnest possible slice>`.
4. **US2...** — `<remaining stories, in priority order>`.
5. **Hardening** — validation, budget/latency enforcement, edge cases.
6. **Polish / submission** — docs, checklist, release.

---

## Testing gate

- **Test-first:** every story phase writes failing tests before implementation.
- **Gate:** the [pre-push hook](.githooks/pre-push) runs [scripts/gate.sh](scripts/gate.sh) — lint,
  type checks, the fast suite, and the placeholder, secret, vulnerability and duplication scans; CI
  re-runs it plus anything too slow/expensive for local (integration, latency, real-model smoke tests).

See [docs/testing-strategy.md](docs/testing-strategy.md).
