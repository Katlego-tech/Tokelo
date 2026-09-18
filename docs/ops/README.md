# Operations

How a Secret Realm project runs once it's live (DESIGN.md §3 rows 12 and 13): service level
objectives, error budgets, telemetry, incidents, and the scheduled checks that keep a quiet
project safe.

| File | What it's for |
|---|---|
| `slo.toml` | each service's objectives; the release's watch window measures them |
| `runbook.md` | how to operate each service: deploy, roll back, read its signals, answer its alerts |
| `observability.md` | the OpenTelemetry baseline every service follows |
| `incidents/INC-nnnn.md` | one per incident, opened by the pipeline or by hand from `incident.template.md` |
| `metrics.md` | the monthly delivery and maintenance numbers, written by `realm dora` |
| `retirement.md` | the checklist for switching a service off for good |

## The error-budget rule

Each objective leaves a budget: 99.5% availability over 28 days allows 0.5% of requests to fail.
**When a service's budget for the window is spent, feature work on it stops.** The next tasks are
corrective (`fix`) or preventive (`test`, `chore(harden)`) until the budget recovers. This is in
AGENTS.md, so every AI session follows it too. A rising share of corrective work in `metrics.md`
is the early warning.

## Incidents

- **Opened** by the release pipeline when the watch window rolls a release back, or by hand from
  `incident.template.md` for anything users noticed.
- **Blameless:** the postmortem asks what in the system let it happen, never who.
- **Closed only with a change:** an incident closes when "The change that stops it recurring"
  names the commit or PR that changed a file (a test, a check, a limit, an alert). `realm
  incidents` checks this in the gate. It's Cultivation's retrospective rule: only a change to a
  file changes the outcome.
