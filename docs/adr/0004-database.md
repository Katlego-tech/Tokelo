# ADR-0004 — The database is Aurora PostgreSQL Serverless v2, pausing at 0 ACU, in one AZ

- Status: superseded by ADR-0011
- Date: 2026-09-19 · Deciders: Katlego

## Context

The specification names Amazon RDS for PostgreSQL, Multi-AZ, for tenant profiles, lease clauses,
incident logs and the SHA-256 digests of evidence. Relational is right for this data. Multi-AZ,
and an instance that runs all the time, don't fit the free plan: about USD 19 a month for
everything, for two environments (ADR-0003).

On-demand prices in `eu-west-1`, from the AWS Pricing API on 2026-09-19, per environment and month:

| Database | While nobody uses it | While in use |
|---|---|---|
| RDS PostgreSQL `db.t4g.micro`, single-AZ, 20 GB gp3 | $14.95 (it can be stopped for 7 days at most, then it starts itself) | the same |
| The same, Multi-AZ | about $30.60 | the same |
| Aurora PostgreSQL Serverless v2, minimum 0 ACU | storage only: $0.11 per GB | $0.14 per ACU-hour, plus I/O |

Aurora Serverless v2 with a minimum capacity of 0 ACUs pauses after 5 minutes to 24 hours
without a connection. A paused instance costs nothing for compute. The first connection resumes
it, typically in about 15 seconds, or 30 seconds or more after more than a day asleep (AWS's
"Scaling to Zero ACUs with automatic pause and resume" page). It needs Aurora PostgreSQL 16.3,
15.7, 14.12 or 13.15 at least. An open connection, or an RDS Proxy, keeps it awake.

## Options considered

1. **Do nothing: the spec's RDS Multi-AZ.** About $61 a month for two environments, three times
   the budget.
2. **RDS `db.t4g.micro`, single-AZ.** About $30 a month for two. Stopping it by hand doesn't
   last, because it starts itself after 7 days.
3. **Aurora PostgreSQL Serverless v2, 0 ACU minimum, one instance** (chosen). It's still
   PostgreSQL in Amazon RDS, it costs nearly nothing idle, and it scales when used.
4. **DynamoDB.** Always free for 25 GB, but it isn't relational, and the specification's schema
   (clauses, incidents, digests, and the joins between them) is.

## Decision

**Aurora PostgreSQL Serverless v2, engine 16 (16.3 or later), minimum 0 ACU, maximum 2
ACU, pausing after 10 minutes idle, one writer instance and no reader, in both environments.**

- Connections use **IAM database authentication**: the token is signed locally, so functions
  inside the VPC need no Secrets Manager endpoint (ADR-0003).
- The master password is `manage_master_user_password = true`, so it never enters the Terraform
  state. Only migrations use it.
- The cluster is encrypted with the AWS-managed RDS key, and deletion protection is on in
  production.

Multi-AZ, a reader in a second AZ with failover priority 0 or 1 that pauses with the writer, is
the documented upgrade if the account moves to the paid plan.

## Consequences

- **The first request after a pause waits about 15 seconds.** The API's clients and the
  functions' database connections allow at least 30 seconds, and retry a failed connection three
  times, as AWS recommends. The NFR for API latency is stated for a warm system, and a separate
  one covers the first request after idle.
- **Nothing may hold a connection open while idle.** Functions open a connection per invocation
  and close it, with no pool that outlives the invocation and no RDS Proxy. Otherwise the
  database never pauses, and costs $0.14 or more an hour.
- **Scheduled jobs don't wake it.** Anything periodic runs as a scheduled Lambda that connects,
  not as `pg_cron`.
- The release pipeline's smoke checks resume staging on every release. That's expected, and cheap.
- The spec's "Multi-AZ" is recorded here as a cost decision, with the upgrade path above.
