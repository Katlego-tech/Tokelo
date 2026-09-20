# ADR-0011 — The store is DynamoDB, in two tables reached through a gateway endpoint

- Status: accepted
- Date: 2026-09-20 · Deciders: Katlego

## Context

ADR-0004 chose Aurora PostgreSQL Serverless v2 pausing at 0 ACU, and ADR-0008 chose the RDS Data
API for its migrations. On 2026-09-20 the first `terraform apply` of staging's database was
refused:

```
FreeTierRestrictionError: To use Aurora clusters with free plan accounts you need to set
WithExpressConfiguration. To remove all limitations, upgrade your account plan.
```

AWS's documentation (the Aurora User Guide, "Amazon Aurora on the AWS Free Tier" and "Create with
express configuration", read 2026-09-20) says what that means:

- On a free-plan account, **only clusters created with express configuration exist**; full
  configuration is refused. That is the whole of ADR-0004's design.
- An express cluster **cannot be associated with a VPC**, and its **internet access gateway
  cannot be disabled**. It is reachable from the internet, by IAM authentication only.
- It also can't take a chosen engine version, a managed master password, or a customer key, and
  is capped at 4 ACU and **1 GiB of storage**, with 2 clusters per account.
- The Terraform AWS provider 6.65 has no `with_express_configuration` argument, so Terraform
  can't create one at all: it would be made by hand and imported.

A database on the public internet contradicts **REQ-018**, which says the functions that reach
the database, and the database itself, have no route to or from the internet. It also ends the
project's plainest piece of security evidence — a VPC with no way out — for the sake of a
database with a gigabyte of room.

The other free-plan-compatible relational option, RDS `db.t4g.micro` in the VPC, is allowed, but
costs about USD 15 a month per environment: about USD 78 for staging alone before the plan ends
on 2027-02-26, against USD 100 of credits, and it can't pause (ADR-0004).

So the constraint that chose Aurora has moved: what the free plan offers is no longer a
relational database this architecture can use. Katlego decided on 2026-09-20 to store the data in
**DynamoDB** instead.

What has to hold, whatever the store:
- every record belongs to exactly one tenant, and no tenant can read another's (REQ-001)
- a digest, once written, never changes (REQ-008)
- the audit log can be appended to and read, never changed or deleted (REQ-011)
- deleting an account leaves nothing personal behind (REQ-016)
- a job delivered twice changes nothing (ADR-0007)
- the functions keep no route to the internet (REQ-018)

## Options considered

1. **Do nothing: keep ADR-0004.** The apply fails. Not an option.
2. **Aurora with express configuration.** Nearly free and it is what AWS offers this account, but
   the database sits on the internet, the VPC becomes pointless (the functions would need a NAT
   gateway at USD 32 a month to reach it, or leave the VPC), REQ-018 has to be rewritten to mean
   less, and Terraform can't create it, so the infrastructure stops being reproducible from code.
3. **RDS `db.t4g.micro`, single-AZ, in the VPC.** Keeps every decision and requirement as
   written, but spends most of the remaining credits on an instance that runs all night doing
   nothing, and the scheduled stop that would fix that leaves the product broken until someone
   starts it.
4. **DynamoDB** (chosen). It has no server, no VPC placement and no idle cost; the first 25 GB of
   storage are in the free tier, and requests are charged per request, which at this project's
   volumes is fractions of a cent. A **gateway endpoint** for DynamoDB costs nothing and is a
   route, not an address, so the functions reach it **without leaving the VPC and without any
   route to the internet**: REQ-018 stands exactly as written, with S3's gateway endpoint beside
   it. ADR-0004 rejected DynamoDB because the specification's schema is relational; §"Decisions"
   in [domain-model.md](../design/domain-model.md) says how that schema becomes two tables
   without losing a rule.

## Decision

**Tokelo stores its data in Amazon DynamoDB: two on-demand tables per environment, reached from
the functions through a DynamoDB gateway endpoint.** This supersedes ADR-0004 and ADR-0008.

| | |
|---|---|
| `tokelo-<env>` | everything a tenant owns: the tenant, documents and their capture metadata, leases, pages, clauses, flags, timeline entries and dossiers. Partition key `pk` = `TENANT#<tenant id>`, sort key `sk` = the record's path under it |
| `tokelo-<env>-audit` | the audit log. Partition key `pk` = `SUBJECT#<pseudonym>`, sort key `sk` = `<when>#<ulid>` |

- **Tenant isolation is the partition key.** Every read and write of tenant data names
  `TENANT#<the token's sub>`, so a query can't reach across tenants ([domain-model.md](../design/domain-model.md) §3).
- **On-demand capacity,** so an idle environment costs storage alone, and nothing has to be sized.
- **Encrypted with the AWS-owned key,** which is DynamoDB's default and free; point-in-time
  recovery on in production only, where it costs per GB.
- **Append-only is an IAM decision, not a table setting:** the functions' policies allow
  `PutItem` on the audit table and nothing else — no `UpdateItem`, no `DeleteItem` — and the
  `PutItem` carries `attribute_not_exists(pk)`, so an entry can't be overwritten either.
- **Once-only writes are condition expressions:** a digest is written with
  `attribute_not_exists(sha256)`, and a document is created with `attribute_not_exists(pk)`, so a
  job delivered twice is a no-op (ADR-0007).
- **No migrations, and no migration path out of the VPC.** The tables are Terraform resources;
  the shape of an item belongs to the code that writes it (`src/tokelo/core/model.py`), and is
  checked by the tests, not by the database. ADR-0008's problem — a function inside the VPC that
  can't read a secret — disappears with the secret.
- **The `db` security group, the DB subnets and the subnet group go with Aurora.** The VPC keeps
  its app subnets, its route tables with no `0.0.0.0/0` route, and now two gateway endpoints.

## Consequences

- **What gets easier.** No connection to open, so nothing waits 15 seconds for a database to
  resume, and the NFR for the first request after idle is about Lambda's cold start alone. No
  password anywhere, no Secrets Manager, no Data API, no migration job in the release, and no
  PostgreSQL container in the integration tests: DynamoDB Local takes its place.
- **What gets harder.** The joins the relational model gave for free are now the key design's
  job: a query per aggregate, and the item's path under its tenant is the contract. Aggregates
  that a report would have joined — a dossier's documents, a clause's flags — are stored with
  their parent. Nothing enforces a foreign key, so the code and its tests do.
- **Cascading deletion is code.** `ON DELETE CASCADE` is gone: deleting an account queries the
  tenant's partition and deletes it in batches, and deletes the pseudonym mapping so the audit
  entries are left anonymous (REQ-016, T048).
- **A transaction across tenants isn't possible, and isn't needed.** Where two writes must land
  together — a document and its timeline entry — they are in one partition, so
  `TransactWriteItems` covers them.
- **Item size.** DynamoDB holds 400 KB per item. A page's text and a clause's text are stored as
  their own items for that reason ([domain-model.md](../design/domain-model.md) §6), and anything
  larger stays in S3, as it already does.
- **The specification named Amazon RDS.** This is a deliberate, recorded departure, forced by what
  the free plan allows; SPEC.md's deviations table carries it, as ADR-0002 and ADR-0003 are
  already carried there.
- **Cost:** storage inside the free tier's first 25 GB, requests at fractions of a cent a month
  at this project's volumes, and USD 0 for the gateway endpoint — against USD 15 a month for the
  cheapest relational alternative.
