# ADR-0008 — Schema migrations run through the RDS Data API, from the infrastructure workflow

- Status: proposed
- Date: 2026-09-19 · Deciders: Katlego

## Context

ADR-0002's consequences say migrations run "as a Lambda function inside the VPC (the api image,
with another handler), started by the pipeline". Two accepted decisions make that impossible as
written:

- **ADR-0003:** a function inside the VPC can't call any AWS API except S3, and that includes
  Secrets Manager.
- **ADR-0004:** the master password is managed by RDS in Secrets Manager
  (`manage_master_user_password`), and only migrations may use it.

So a migration function inside the VPC can't read the password it needs. The alternative, giving
the application functions a database role that can change the schema, puts the power to drop
tables inside every function a request reaches.

The Aurora cluster can instead take SQL over HTTPS, through the **RDS Data API**, authenticated
with IAM and the managed secret.
- **Availability:** in `eu-west-1`, for Aurora PostgreSQL 16.1 and later (AWS's "Supported Regions
  and Aurora DB engines for RDS Data API" page, 2026-09-19), so ADR-0004's 16.3 or later has it.
- **Pausing:** a call resumes a paused instance, and doesn't stop it from pausing again (AWS's
  auto-pause page).

This ADR replaces ADR-0002's consequence about migrations. ADR-0002's decision, every service on
Lambda, stands.

## Options considered

1. **Do nothing: a migration function inside the VPC.** It can't reach the secret, so it doesn't
   work.
2. **An interface endpoint for Secrets Manager.** That's $8.03 a month per AZ, only so a rare
   migration can read one secret (ADR-0003's budget has no line for it).
3. **The `api` connects, when migrating, as a database role that owns the schema.** It works
   without the secret, but every request to the `api` then runs in a function that can drop the
   schema.
4. **The RDS Data API, from the `realm-infra` workflow's apply job** (proposed). This runs
   outside the VPC, with the apply role, which already has broad rights (`PowerUserAccess`), and
   the managed secret. Migrations live under `infra/`, so the workflow already runs on them, and
   they're reviewed with the plan like any other infrastructure change.

## Decision

Proposed: **migrations are SQL files in `infra/db/migrations/`, applied in order through the RDS
Data API (`aws rds-data execute-statement` in a transaction), as the master user, by the
`realm-infra` apply job after `terraform apply`.** The staging apply runs on merge, and the
production apply runs by hand, as it already does.

- The cluster has the Data API turned on (`enable_http_endpoint = true`).
- A table, `schema_migrations`, records what has run, so a repeated apply is a no-op.
- The first migration creates the application's database user, which logs in with IAM
  (`GRANT rds_iam`). It can read and write the tables, and INSERT into the audit log but never
  UPDATE or DELETE there.

## Consequences

- **The functions only ever connect as the application user.** Nothing a request reaches can
  change the schema.
- **Migrations are applied when infrastructure is applied,** which may be before the code that
  uses them is released. Each migration must work with the code before it and after it:
  - add, then use, then drop, over separate releases
  - never rename in place
- `T023` writes the first migration and the script that applies it (`scripts/migrate.py`: the AWS
  CLI called from Python's standard library, as the kit does). The apply job runs it.
- The Data API costs per request, and a migration is a few requests. That's cents over the
  project's life. ADR-0003's budget table is unchanged.
