# `Tokelo` — Specification (the WHAT)

**Related:** [PLAN.md](PLAN.md) (the HOW) · [TASKS.md](TASKS.md) (the backlog)

---

## Overview

`<Two or three sentences: what the system is, who/what calls it (a human user? an automated
harness? both?), and what it produces.>`

### Goals

- `<the core things the system must do>`

### Non-goals

- `<explicitly out of scope — this list prevents scope creep more than the goals list does>`

---

## Actors

### `<Primary actor — e.g. "the end user" or "the evaluation harness">`

`<What it does, step by step: what it sends in, what it expects back, how it judges success.>`

> 📝 **Customize:** if there's a scoring/evaluation rubric (hackathon, grading, SLA), spell it out here —
> it drives every acceptance criterion below.

---

## User stories

> 📝 **Customize:** number them `US1, US2, ...`, prioritize `P1/P2/P3`, and write each as independently
> testable and independently demoable — this is what makes phased delivery ([PLAN.md](PLAN.md) §Build
> phases) actually work instead of being a "big bang" in disguise.

A story title needs a **verb and an object** — "Refuse to launch into a full world", not "World
fixes". A title you can't act on is a story nobody understood well enough to build.

### US1 — `<title>` (P1)

**As a** `<actor>`, **I want** `<capability>`, **so that** `<value>`.

**Scenarios** — each becomes an acceptance test
([docs/testing-strategy.md](docs/testing-strategy.md#acceptance-tests-start-with-a-story)), and a
task's `Verify:` line names the scenario it satisfies:

```
Scenario: <name — the case, not the mechanism>
  Given <starting state>
  When  <the action>
  Then  <the observable outcome>
```

- **Scenario: `<the happy path>`** — Given `<...>`, when `<...>`, then `<...>`.
- **Scenario: `<the edge that breaks it>`** — Given `<...>`, when `<...>`, then `<...>`.

> A story with one scenario is usually a story with an unexamined edge case. Write the boundary and
> the refusal too — "the world is full", "the file is empty", "the key is expired" — because those
> are the cases the implementation will otherwise decide for itself, silently.

**Acceptance criteria:**
- [ ] `<observable, testable criterion>`

---

## Acceptance criteria (system-level)

- [ ] `<the criteria that gate "this is done", independent of any one user story>`
