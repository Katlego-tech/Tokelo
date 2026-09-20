# `Tokelo` — Implementation Plan (the HOW)

**Companions:** [SPEC.md](SPEC.md) (the WHAT) · [docs/design/](docs/design/) (the shapes) ·
[TASKS.md](TASKS.md) (the task list) · [docs/adr/](docs/adr/) (the decisions)

---

## Summary

Tokelo is serverless and event-driven, on AWS in `eu-west-1`, built with the Secret Realm kit
(**standard** tier, **aws** platform).

- A React web app signs tenants in with Cognito, and calls an HTTP API whose `api` function runs
  on Lambda.
- Files go straight to S3 through pre-signed URLs. Every job, whether an upload or a request the
  API writes, starts as an object in S3. EventBridge carries it to an SQS standard queue (ADR-0007) with a
  dead-letter queue, and a worker function takes it from there: `ocr`, `evidence` or `dossier`.
- The functions are in private subnets with no way to the internet; they reach S3 and DynamoDB
  through gateway endpoints. The store is DynamoDB, which has no server and nothing idle.

**The key technical bet:** everything scales to zero, so both environments fit the **AWS free
plan: about USD 19 a month until the plan ends on 2027-02-26** (ADR-0002 to ADR-0004). **The
hard constraints:** the grounding rule, POPIA, the free plan, and a deadline before 2027-02-26.

---

## Non-negotiables (project principles)

1. **The grounding rule.** Never state, cite or paraphrase a statute, section, time limit or case
   that isn't in the curated sources:
   - the Rental Housing Act 50 of 1999
   - the Consumer Protection Act 68 of 2008, sections 14 and 48
   - the PIE Act 19 of 1998

   Never present legal information as legal advice. A test holds every explanation and answer to
   this (REQ-006).
2. **The budget.** AWS cost, not counting credits, of at most USD 20 a month (NFR-008). Nothing
   may move the account to the paid plan: no AWS Organization, no Control Tower. A change that
   adds an hourly cost (a NAT gateway, an always-on container, a second database instance) needs
   an ADR first.
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
8. **Real tenant documents never enter the repository.** Test samples are synthetic.

---

## Technical Context

| Dimension | Value |
| --- | --- |
| **Language(s) + versions** | Python 3.14, the newest Lambda runtime that isn't in preview (AWS's Lambda runtimes page, checked 2026-09-19); the web app's toolchain is pinned in its design doc |
| **Architecture** | Event-driven and serverless: an HTTP API on Lambda, and worker functions fed by SQS. Every service is a Lambda container image (ADR-0002). This replaces setup's first answer, an API on ECS Fargate |
| **Messaging / async** | EventBridge to Amazon SQS standard queues, each with a dead-letter queue after 3 failures, and idempotent workers (ADR-0007). Jobs start as objects in S3 (ADR-0003) |
| **Frontend** | React + shadcn/ui (Radix + Tailwind + CVA), served by the `api` function from its image (ADR-0010); the toolchain is pinned in [docs/design/web.md](docs/design/web.md) |
| **Containerization** | One container image per service, built, scanned, signed and deployed by digest by the kit's release pipeline. Local development runs them with Docker |
| **Runtime/deploy target** | AWS Lambda in `eu-west-1`, in a staging and a production environment in one account, deployed by the kit's `aws` adapter through GitHub OIDC roles |
| **Data layer** | DynamoDB, two on-demand tables reached through a gateway endpoint (ADR-0011); S3 for documents (private, SSE-KMS) |
| **Key external services/models** | Amazon Cognito, API Gateway (HTTP API), EventBridge, SQS, S3. OCR with pypdf and Tesseract 5, English only (ADR-0009). No Textract, and no language model in phases 1–5 (ADR-0006) |
| **Testing** | pytest, with `@pytest.mark.req`; ruff, pyright; in the release pipeline, k6 (performance), pa11y (accessibility) and ZAP (DAST) |
| **Perf/cost goals** | NFR-001 to NFR-009 in [REQUIREMENTS.md](REQUIREMENTS.md). In short: an upload URL at p95 < 500 ms warm; the first request after a pause within 30 s; a digital lease's flags within 2 minutes; at most USD 20 a month |
| **Constraints** | The AWS free plan (no Organizations; it ends 2027-02-26). `eu-west-1`, with the POPIA section 72 transfer stated in the privacy notice (ADR-0001). No NAT, so nothing inside the VPC calls the internet or other AWS APIs (ADR-0003). The grounding rule |
| **Scale** | An elective project: tens of tenants, a few hundred lease pages and a few GB of evidence a month. The limits in REQ-003 (20 MB and 30 pages per file) bound a single job |

---

## Project structure (as scaffolded)

The application's folders (`services/…`, `web/`) come with Phase 1. The long version is in
[docs/project-structure.md](docs/project-structure.md).

```
Tokelo/
├── REQUIREMENTS.md  SPEC.md  PLAN.md  TASKS.md  GATES.md  STATUS.md  AGENTS.md  CLAUDE.md
├── realm.toml               the realm's settings: tier, platform, region, and later the services
├── cosign.pub               the release-signing public key
├── docs/
│   ├── adr/                 ADR-0001 to ADR-0006, accepted
│   ├── architecture/        C4 context and containers
│   ├── design/              one design doc per lane (next)
│   ├── ops/  release/  security/
│   └── …                    the kit's guides
├── infra/                   Terraform: bootstrap/, envs/{staging,production}/, modules/
├── scripts/                 gate.sh, realm/ (the kit's tools)
└── .github/workflows/       ci, realm-release, realm-promote, realm-infra, realm-scheduled
```

---

## Design documents

The diagrams implementation is built and reviewed against. One per non-trivial lane, merged before
that lane's implementation tasks are written — see
[docs/design-documentation.md](docs/design-documentation.md). These are the next planning PR's.

| Lane | Design doc | Covers |
| --- | --- | --- |
| domain model | [docs/design/domain-model.md](docs/design/) | the core entities: tenant, lease, page, clause, flag, rule, evidence, timeline entry, dossier, audit entry (class diagram) |
| `api` | [docs/design/api.md](docs/design/) | the endpoints, pre-signed URLs, job requests, authorization (contracts, sequence) |
| `ocr` | [docs/design/ocr.md](docs/design/) | text layer, OCR, clause splitting, the rule catalogue (sequence, state) |
| `evidence` | [docs/design/evidence.md](docs/design/) | digests, EXIF, verification, the audit log (sequence) |
| `dossier` | [docs/design/dossier.md](docs/design/) | the PDF's structure, the timeline (sequence) |
| navigator | [docs/design/navigator.md](docs/design/) | the curated topics, and how questions match them (state) |
| web | [docs/design/web.md](docs/design/) | screens and flows, the privacy notice, the resume wait (flow) |
| infrastructure | [docs/design/infrastructure.md](docs/design/) | the VPC, subnets, security groups, queues and events (deployment) |

---

## Build phases (MVP-first)

Mirrors [TASKS.md](TASKS.md). Each phase should be independently demoable at its checkpoint. The
specification's own milestones are in brackets.

0. **Design:** ADRs and requirements (done), then the domain model and a design doc per lane.
1. **Setup:** the service skeletons with their health handlers, the web app skeleton, the test
   config, and the four `[[service]]` entries in `realm.toml`. Then the AWS bootstrap, the
   `v0.0.0` seed, and the staging infrastructure: VPC, subnets, S3, queues, the tables and Cognito
   (spec phase 1).
2. **Foundational:** the curated sources, the schema, sign-in and authorization (REQ-001),
   pre-signed uploads (REQ-002), and S3 → EventBridge → SQS with dead-letter queues (REQ-017)
   (spec phase 2, without Textract).
3. **US1, check a lease:** the text layer and Tesseract, the rule catalogue and its explanations
   (spec phases 2 and 3).
4. **US2, evidence:** digests, EXIF, verification, the audit log (spec phase 4).
5. **US3, the dossier** (spec phase 4).
6. **US4, the navigator.**
7. **Hardening and release:** account deletion, the NFRs measured, the gates, UAT, production
   (spec phase 5).

---

## Testing gate

- **Test-first:** every story phase writes failing tests before implementation.
- **Gate:** the [pre-push hook](.githooks/pre-push) runs [scripts/gate.sh](scripts/gate.sh) — lint,
  type checks, the fast suite, and the placeholder, secret, vulnerability and duplication scans; CI
  re-runs it plus anything too slow/expensive for local (integration, latency, real-model smoke tests).

See [docs/testing-strategy.md](docs/testing-strategy.md).
