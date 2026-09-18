# `tokelo` — Stage gates

**Requirements:** [REQUIREMENTS.md](REQUIREMENTS.md) · **Releases:** [docs/releases/](docs/releases/)

> Each lifecycle stage ends at a decision gate (ISO/IEC/IEEE 12207). A gate passes when a dated
> entry below records the evidence for its exit criteria; in the assured tier the entry is also
> signed by whoever made the decision. `scripts/realm/realm gates` checks this file, and the
> release workflow refuses to release until the Development gate has passed.
>
> An entry reads:  `- Passed: 2026-10-01 · Evidence: <links, commits, reports> · Signed: <name>`
> A gate passes only after the one before it.

## Concept

**Exit criteria:**
- SPEC.md and the operational concept describe the same problem and the same users
- the business and stakeholder requirements are approved
- PLAN.md names the tier, the platform and the budget

<!-- - Passed: YYYY-MM-DD · Evidence: … · Signed: … -->

## Development

**Exit criteria:**
- every requirement in the first release is approved, with its tasks and tests (`realm trace`)
- C4 levels 1 and 2 match the code; an accepted ADR for each decision the build rests on
- every design doc has its threats worked out; the gate is green on `main`

<!-- - Passed: YYYY-MM-DD · Evidence: … · Signed: … -->

## Release

**Exit criteria:**
- a release record in `docs/releases/` with every release check passed and a UAT sign-off
- the service level objectives in `docs/ops/slo.toml` held through the watch window

<!-- - Passed: YYYY-MM-DD · Evidence: … · Signed: … -->

## Operation

**Exit criteria:**
- on-call, the runbook and the incident process in `docs/ops/` in use
- an error budget tracked for every service level objective

<!-- - Passed: YYYY-MM-DD · Evidence: … · Signed: … -->

## Retirement

**Exit criteria:**
- users told, data exported or deleted as promised, and the service stopped
- the retirement checklist in `docs/ops/` completed

<!-- - Passed: YYYY-MM-DD · Evidence: … · Signed: … -->
