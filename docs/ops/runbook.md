# `tokelo` — Runbook

<!-- One section per [[service]] in realm.toml. Write it for someone woken up at 3am who has never
     seen this service: exact commands, where to look, what "normal" looks like. -->

## <service>

**What it does:** <one line>. **Depends on:** <databases, other services, third parties>.
**Objectives:** `docs/ops/slo.toml` (<availability %>, <p95 ms>).

### Deploy and roll back

- Release: tag `vX.Y.Z` (realm-release), then realm-promote after the UAT sign-off.
- Roll back: `bash scripts/realm/release.sh rollback <earlier version>`, or the realm-promote
  workflow for that version. Every release record ends with the command for its own version.

### Signals

- **Dashboards:** <link>
- **Logs:** <where, and how to filter to this service>
- **Traces:** <link>; every span carries `service.version`, the release, and `deployment.environment`.

### Alerts, and what to do

| Alert | Means | First steps |
|---|---|---|
| <error budget burning fast> | <the objective will break within hours> | <look at the last release; roll back if it's the cause> |

### Known failure modes

- <what has gone wrong before, how it looked, what fixed it; link the INC record>
