# Design — the infrastructure

**Status:** agreed · **Owner:** Katlego · **Tasks:** T005, then T016–T021, T023 (the store),
T026, T051 · **Spec:** [SPEC.md](../../SPEC.md), the evaluator's four competencies

---

## 1. What this covers

Every AWS resource Tokelo runs on in one environment:
- the network, the tables and the documents bucket
- the event rules, the queues and the functions' settings
- the user pool, and the HTTP API, which also serves the web app (ADR-0010)
- the alarms, and what each resource costs

Staging and production are the same design with different values (§6).

It doesn't cover:
- what the bootstrap creates, the CI roles, the Terraform state and the budget: the kit's
  `infra/bootstrap/`, run in T016
- what the functions do: the lane docs

## 2. Reference material

| Kind | Where |
| --- | --- |
| Decisions | ADR-0001 (`eu-west-1`), ADR-0002 (Lambda), ADR-0003 (no way out of the VPC), ADR-0007 (standard queues), ADR-0011 (DynamoDB, superseding ADR-0004 and ADR-0008) |
| Requirements | REQ-002, REQ-017, REQ-018, REQ-019, NFR-007, NFR-008 |
| The kit | `infra/README.md`, `infra/modules/realm-lambda` (functions, aliases, log groups), and the bootstrap's roles and permissions boundary (the kit's DESIGN.md §14) |
| Prices | ADR-0003's budget, from the AWS Pricing API on 2026-09-19 |

## 3. Domain model

Not applicable: this lane has resources, not entities. §4's diagram and §6's tables are its
model.

## 4. Flow

### What's deployed, and what can reach what

```mermaid
flowchart LR
    tenant([Tenant's browser])
    subgraph edge[AWS services, outside the VPC]
        gw[API Gateway<br/>HTTP API + JWT authorizer]
        cog[Cognito<br/>user pool]
        s3[(S3 documents bucket<br/>private, SSE-KMS, versioned)]
        ddb[(DynamoDB<br/>tokelo-env, tokelo-env-audit)]
        eb[EventBridge<br/>default bus rules]
        q[SQS standard queues<br/>lease, page, evidence, dossier<br/>+ 4 dead-letter queues]
    end
    subgraph vpc[VPC: no internet gateway, no NAT]
        subgraph app[App subnets, 2 AZs]
            api[api]
            ocr[ocr]
            ev[evidence]
            dos[dossier]
        end
        gs3[S3 gateway endpoint]
        gdb[DynamoDB gateway endpoint]
    end
    tenant --> cog
    tenant -- web app and /api/ --> gw --> api
    tenant -- pre-signed POST --> s3
    s3 --> eb --> q
    q -- event source mappings --> ocr & ev & dos
    api & ocr & ev & dos --> gdb --> ddb
    api & ocr & ev & dos --> gs3 --> s3
```

The functions sit in the VPC, but Lambda itself does the invoking, the queue polling, the image
pulling and the log shipping, outside it (ADR-0003). The only things leaving the app subnets are
HTTPS to S3 and to DynamoDB, both through gateway endpoints — routes on AWS's own network, not
addresses on the internet (ADR-0011).

**Failure paths:**
- **A job fails three times:** it goes to its dead-letter queue. The worker marks the item
  `failed` when `ApproximateReceiveCount` reaches 3 and the job still fails. A CloudWatch alarm
  on each dead-letter queue emails the operator.
- **A conditional write is refused:** the item already holds what the worker would have written,
  so the job was done before. The worker treats that as success and deletes the message
  (ADR-0007, ADR-0011).
- **Too many jobs at once:** each trigger's maximum concurrency caps how many run. The rest wait
  in the queue, and nothing is dropped.

## 5. State

Not applicable: no resource here has states that the application moves between. A DynamoDB table
is either there or it isn't; there is nothing to resume (ADR-0011).

## 6. Contracts

### The network (per environment)

| Resource | Staging | Production | Notes |
|---|---|---|---|
| VPC | `10.20.0.0/16` | `10.21.0.0/16` | DNS hostnames and support on; **no internet gateway** |
| App subnets | `10.20.1.0/24` (a), `10.20.2.0/24` (b) | `10.21.1.0/24`, `10.21.2.0/24` | the functions, in two zones |
| Route tables | local only, plus the two gateway endpoints on the app subnets' | the same | **no `0.0.0.0/0` route anywhere** (REQ-018) |
| S3 gateway endpoint | on the app route table | the same | free |
| DynamoDB gateway endpoint | on the app route table; its policy names this environment's two tables | the same | free (ADR-0011) |
| Security group `fn` | no inbound; outbound TCP 443 to S3's and DynamoDB's prefix lists | the same | every function |

### The tables (ADR-0011)

Two tables per environment, on-demand, with the keys [domain-model.md](domain-model.md) §3 sets.

| Table | Keys | Settings |
|---|---|---|
| `tokelo-<env>` | `pk` (string), `sk` (string) | on-demand; encrypted with the AWS-owned key; point-in-time recovery in production only; deletion protection in production only; no secondary index |
| `tokelo-<env>-audit` | `pk` (string), `sk` (string) | the same, and the functions may only `PutItem` on it (REQ-011) |

- **Nothing is provisioned and nothing is idle-charged:** an environment nobody uses costs its
  stored bytes, and the first 25 GB are in the free tier.
- **The tables are reached through the DynamoDB gateway endpoint,** so the functions need no
  route to the internet (REQ-018). The endpoint's policy allows only these two tables, so a
  function that was tricked into naming another table is refused by the network as well as by IAM.
- **There is no schema and no migration.** `src/tokelo/core/model.py` is the item shape and
  `core/store.py` the only code that writes it (T023).

### The documents bucket

| Setting | Value |
|---|---|
| Name | `tokelo-<env>-documents-<account id>` |
| Access | Block Public Access, all four settings; object ownership `BucketOwnerEnforced`; a bucket policy denying any request without TLS |
| Encryption | SSE-KMS with the AWS-managed `aws/s3` key and a bucket key: no USD 1-a-month customer key |
| Versioning | on. Earlier versions expire after 30 days; account deletion removes every version (T048) |
| Lifecycle | `jobs/` objects expire after 7 days; uploads and dossiers stay until the tenant deletes them |
| CORS | `POST` from the HTTP API's own origin only, where the web app is served (ADR-0010) |
| Events | EventBridge notifications on |

### Events and queues (ADR-0007)

| EventBridge rule on the default bus: S3 "Object Created" in the documents bucket, key matching | Target queue | Worker |
|---|---|---|
| `uploads/*/lease/*` | `tokelo-<env>-lease` | `ocr` (splits the lease into page jobs) |
| `jobs/page/*` | `tokelo-<env>-page` | `ocr` (reads one page) |
| `uploads/*/photo/*`, `uploads/*/notice/*`, `uploads/*/chat/*` | `tokelo-<env>-evidence` | `evidence` |
| `jobs/dossier/*` | `tokelo-<env>-dossier` | `dossier` |

- Each queue is **standard**, with its own dead-letter queue after **3 receives**. Messages are
  kept 4 days in the queue and 14 in the dead-letter queue.
- The visibility timeout is 6 times the function's timeout.
- Each queue's policy accepts messages only from its rule's ARN.

### The functions (the kit's `realm-lambda` module)

| Function | Memory | Timeout | Temporary storage | Trigger | Visibility timeout |
|---|---|---|---|---|---|
| `tokelo-<env>-api` | 512 MB | 29 s (under the HTTP API's 30 s) | 512 MB | API Gateway | none |
| `tokelo-<env>-ocr` | 2,048 MB | 120 s | 1,024 MB | the lease and page queues | 720 s |
| `tokelo-<env>-evidence` | 512 MB | 60 s | 512 MB | the evidence queue | 360 s |
| `tokelo-<env>-dossier` | 1,024 MB | 300 s | 2,048 MB | the dossier queue | 1,800 s |

- Every function is in the app subnets, with security group `fn`, amd64, alias `live`, and logs
  kept 30 days.
- **Every function's environment:** `TOKELO_TABLE`, `TOKELO_AUDIT_TABLE` and
  `TOKELO_DOCUMENTS_BUCKET`, so no name is hard-coded in the code. The `api` also gets
  `TOKELO_USER_POOL_ID` and `TOKELO_CLIENT_ID`, which `/config.json` and the CSP read (ADR-0010).
  All of them are set by Terraform (T020); `AWS_REGION` is Lambda's own.
- Each queue trigger reads **one message at a time**, reports the failures in its batch, and has
  a **maximum concurrency of 2**. That's the lowest allowed, and it keeps the write rate and the
  bill small.
- **Each function's role** has the VPC access policy, plus only this:

  | Function | S3 | Tables | SQS |
  |---|---|---|---|
  | `api` | `PutObject` on `uploads/*` (to sign the POSTs) and `jobs/dossier/*`; `GetObject` and `GetObjectVersion` on `uploads/*`, `GetObject` on `dossiers/*`; `ListBucketVersions`, `DeleteObject` and `DeleteObjectVersion` under `uploads/`, `dossiers/` (account deletion) | `GetItem`, `Query`, `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem` and `TransactWriteItems` on `tokelo-<env>`; `PutItem` and `Query` on `tokelo-<env>-audit` | none |
  | `ocr` | `GetObject` and `GetObjectVersion` on `uploads/*/lease/*`, `GetObject` on `jobs/page/*`; `PutObject` on `jobs/page/*` | `GetItem`, `Query`, `PutItem` and `UpdateItem` on `tokelo-<env>`; `PutItem` on `tokelo-<env>-audit` | receive and delete on its two queues |
  | `evidence` | `GetObject` and `GetObjectVersion` on `uploads/*` | the same as `ocr` | receive and delete on its queue |
  | `dossier` | `GetObject` and `GetObjectVersion` on `uploads/*`, `GetObject` on `jobs/dossier/*`; `PutObject` on `dossiers/*` | the same as `ocr` | receive and delete on its queue |

  No function may `DeleteItem` or `UpdateItem` on the audit table, or `Scan` either table: the
  audit log is append-only (REQ-011), and every read names a tenant's partition (REQ-001).

  Every role is named `tokelo-<env>-…` under the `/tokelo/` path, with the bootstrap's
  permissions boundary.

### Identity and the API

| Resource | Settings |
|---|---|
| Cognito user pool | sign-in by email; self sign-up with email verification (Cognito's own sender); MFA optional (TOTP); passwords of at least 12 characters; the Lite feature plan |
| Its app client | the web app's: public, no secret, SRP sign-in; access tokens last 1 hour, refresh tokens 30 days |
| HTTP API | [api.md](api.md) §6's routes: `/api/*` behind a JWT authorizer (the pool as issuer, the app client as audience); `/health`, `/config.json` and the web app's files open (ADR-0010). Lambda proxy integration, payload 2.0; the default route throttled to 10 requests a second, bursting to 20; no CORS, because the app and the API share an origin; access logs kept 30 days |

### The web app

Served by the `api` function from its own image, at the HTTP API's URL (ADR-0010,
[web.md](web.md)). There's no web bucket and no CloudFront.

### Alarms

| Alarm | Fires when | Tells |
|---|---|---|
| Each dead-letter queue | `ApproximateNumberOfMessagesVisible` > 0 | the operator, by email through one SNS topic |
| The budget | 50%, 80% and 100% of USD 20, and 100% forecast | the operator (the bootstrap's; REQ-019) |

### What an environment costs (ADR-0003)

| Resource | Idle | In use |
|---|---|---|
| VPC, subnets, route tables, security groups, both gateway endpoints | $0 | $0 |
| DynamoDB | storage only, and the first 25 GB are in the free tier | per request, fractions of a cent at this scale (ADR-0011) |
| Lambda, API Gateway, SQS, EventBridge, S3, Cognito | $0 | cents at this scale; Lambda within its always-free allowance |
| CloudWatch logs and alarms, SNS email | $0 | cents |

## 7. Structure

| Path | New? | Responsibility |
| --- | --- | --- |
| `infra/modules/tokelo-env/` | new | one environment: everything in §6, so staging and production can't drift apart |
| `infra/modules/tokelo-env/{network,tables,storage,events,functions,identity,api,web,alarms}.tf` | new | one file per §6 table |
| `infra/envs/staging/main.tf`, `infra/envs/production/main.tf` | changed | call `tokelo-env` with the environment's values (CIDRs, protection) |
| `src/tokelo/core/store.py`, `src/tokelo/core/model.py` | new | the items and the only code that reads or writes them (T023); there is no migration to run (ADR-0011) |

## 8. Decisions & alternatives

| Decision | Chosen | Rejected, and why |
|---|---|---|
| One module for both environments | **`tokelo-env`,** called twice | two copies: they drift, and production gets what staging never ran |
| Where the store lives | **DynamoDB, outside the VPC, reached through a gateway endpoint** (ADR-0011) | a database inside the VPC: the free plan will only create an Aurora cluster that sits on the internet, and the relational alternative costs USD 15 a month per environment |
| An internet gateway | **none at all** | one for "later": nothing in the VPC needs it, and its absence is the proof of REQ-018 |
| Keys | **the AWS-managed keys** (`aws/s3`, `aws/rds`) | customer keys: USD 1 each a month, for control this project doesn't use |
| Limiting load | **maximum concurrency on each trigger, and API throttling** | reserved concurrency: it takes from the account's pool, which may be small on a new account (§10) |
| The web app's address | **the HTTP API's own URL** (ADR-0010) | a custom domain: a registration and a Route 53 zone at USD 0.50 a month |
| Tamper-evidence for files | **digests and versioning** | S3 Object Lock: compliance mode would stop account deletion (REQ-016) |

Deviations from [docs/architecture-defaults.md](../architecture-defaults.md): serverless in place
of containers on servers, and no NAT (ADR-0002, ADR-0003).

## 9. How this is verified

- **`realm-infra`'s plan on each infrastructure PR,** and the gate's Terraform checks: fmt,
  validate, tflint, checkov (with a reason for every skip).
- **T051's inspection record:**
  - the deployed route tables have no `0.0.0.0/0` route
  - the DynamoDB endpoint's policy names only this environment's two tables, and no function may `Scan` or delete an audit entry
  - the bucket's Block Public Access settings are on
  - the budget exists as specified
- **T026's integration test on staging:** an object in each prefix reaches its queue, and a
  failing job reaches its dead-letter queue and raises the alarm.

## 10. Open questions

- [ ] **The account's Lambda concurrency limit.** Check it at T018 with
  `aws lambda get-account-settings`. The design needs 9 at most: the `api`, plus 2 for each of
  the four triggers. If the limit is 10, it fits, with no room for reserved concurrency.
  Requesting an increase is free.
- [x] **Which database the free plan allows.** Answered on 2026-09-20, at T018's apply: Aurora
  refuses this account unless the cluster is created outside a VPC, on the internet. The store is
  DynamoDB (ADR-0011).
- [ ] **Cognito's own email sender has a small daily limit.** It's enough for an elective's sign-ups.
  SES is the change if it isn't.

## Threats (STRIDE)

| Threat | STRIDE | Where | Mitigation | Proven by |
|---|---|---|---|---|
| The store is reached from outside the project | Information disclosure | DynamoDB | the tables are reached only through the gateway endpoint, whose policy names them and nothing else; each function's role names the actions it needs; nothing has a route to the internet | T051's inspection (REQ-018) |
| A function is used to send data out | Information disclosure | the app subnets | no route out except S3 and DynamoDB through their gateway endpoints; `fn` allows only 443 to those two prefix lists, and the DynamoDB endpoint's policy names this environment's tables | T051's inspection; the Terraform plan |
| The documents bucket is made public by mistake | Information disclosure | the bucket | Block Public Access; a TLS-only policy | checkov in the gate; T051's inspection |
| A forged message is put on a queue | Spoofing | the SQS queues | each queue's policy accepts only its EventBridge rule's ARN | the Terraform plan; T026's test |
| A stored file is overwritten | Tampering | the documents bucket | versioning keeps the original, and the digest taken on storage detects the change (REQ-010) | tests/api/test_verify.py (T039) |
| A flood of requests or jobs runs up the bill | Denial of service | API Gateway, the triggers, the tables | throttling; maximum concurrency 2 per trigger; on-demand tables that are only charged for what is written; the budget's alerts | the Terraform plan; the budget (T016) |
| A function's role does more than its job | Elevation of privilege | the IAM roles | §6's per-function permissions; the bootstrap's permissions boundary on every project role | checkov in the gate; review against §6 |
| A change to infrastructure goes unrecorded | Repudiation | the account | every change goes through a PR and `realm-infra`'s plan and apply; CloudTrail's event history is on by default | the workflow runs, and GitHub's history |
| Personal data ends up in the logs | Information disclosure | CloudWatch logs | functions log IDs and outcomes, never file contents or names; logs kept 30 days | review of each lane's logging, and the lane docs' threats |
