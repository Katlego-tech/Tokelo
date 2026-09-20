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

- Passed: 2026-09-20 · Evidence: [SPEC.md](SPEC.md) (the problem, the four user stories and the
  operational concept), [REQUIREMENTS.md](REQUIREMENTS.md) (7 business and stakeholder
  requirements with 38 beneath them, reviewed and merged in PR #4), [PLAN.md](PLAN.md) (the
  standard tier, AWS `eu-west-1` on the free plan, and the USD 20 a month budget), and ADR-0001
  to ADR-0003 on where it runs and what it may cost.

## Development

**Exit criteria:**
- every requirement in the first release is approved, with its tasks and tests (`realm trace`)
- C4 levels 1 and 2 match the code; an accepted ADR for each decision the build rests on
- every design doc has its threats worked out; the gate is green on `main`

- Passed: 2026-09-20 · Evidence: ADR-0001 to ADR-0011 accepted and frozen; `realm adr-check`, `design-check` and `trace` all clean; the gate green and required on `main`; staging applied and answering (T018 to T020). Scope and detail below.

  **Scope: the setup release (`v0.1.0`)** — the architecture, the infrastructure and the
  pipeline, not the features.

  - **Decisions:** ADR-0001 to ADR-0011, all accepted and frozen (`realm adr-check`: 11 ADRs);
    ADR-0005 superseded by ADR-0009, ADR-0004 and ADR-0008 by ADR-0011.
  - **Architecture:** C4 levels 1 and 2 in [docs/architecture/](docs/architecture/) match what is
    deployed — four Lambda services, DynamoDB, S3, EventBridge and SQS — and every design doc in
    [docs/design/](docs/design/) has its STRIDE threats (`realm design-check`: 9 documents).
  - **Traceability:** `realm trace` is clean — 38 requirements, 56 tasks, no broken link.
  - **The gate is green on `main`,** and required there: 18 checks across 2 projects, including
    Semgrep, checkov with a reason for every skip, tflint and the Terraform checks.
  - **Staging is applied and answering** (T018–T020): `/health` returns `{"ok": true}`, `/api/`
    without a token returns 401 from API Gateway, and the web app is served at `/`.
  - **What this entry does not cover:** every feature requirement is still `proposed`. None of
    US1–US4 is built, so no requirement has its tests yet, and REQ-018 and REQ-019 are verified by
    inspection in T051 rather than by a test. **T052 reads this gate again for `v1.0.0`,** when
    the first release's requirements are approved with their tasks and tests.

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
