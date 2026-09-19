# ADR-0002 — Every service is a Lambda function, running a container image

- Status: proposed
- Date: 2026-09-19 · Deciders: Katlego

## Context

The specification names "AWS ECS (Fargate) / Lambda" for the application runtime: a Python API
behind API Gateway, and asynchronous workers for OCR, evidence metadata and dossier PDFs fed by
SQS. The handover's first draft of this decision put the API on ECS Fargate and the workers on
Lambda.

That was before the free plan. The credits give about USD 19 a month until 2027-02-26, for
staging and production together (ADR-0003). An always-on container costs money every hour,
whether anyone uses it or not:

| Compute | Idle cost, per environment and month (`eu-west-1`) |
|---|---|
| ECS Fargate, the smallest task (0.25 vCPU, 0.5 GB), one task | $9.01, plus a way out of a private subnet to pull its image and ship its logs (ADR-0003): a NAT gateway (+$35.04) or at least four interface endpoints (+$32.12) |
| Lambda | $0. AWS's always-free allowance covers 1M requests and 400,000 GB-seconds a month; beyond it, $0.0000166667 per GB-second |

The kit supports both runtimes per service (`runtime = "ecs" | "lambda"` in `realm.toml`), and a
web service may run on Lambda.

## Options considered

1. **Do nothing: the handover's split**, with the API on ECS Fargate and the workers on Lambda.
   It's the most "containerized" shape, but it costs $18 a month for two environments before any
   networking, and $88 or more with the NAT gateways. That uses the whole budget in the first month.
2. **Everything on ECS Fargate.** This costs the most while idle, and long OCR jobs gain nothing
   from it.
3. **Everything on Lambda, from container images** (proposed). Idle costs nothing. The functions
   are the same Python, packaged as container images in ECR, so they're still containers the
   release pipeline builds, scans, signs and deploys by digest. The limits: 15 minutes per
   invocation, 10 GB per image, 10,240 MB of memory, and a cold start after idle.

## Decision

Proposed: **every service is a Lambda function running a container image**, deployed by the kit's
`aws` adapter (`runtime = "lambda"`):

| Service | Kind | What it does | Module |
|---|---|---|---|
| `api` | web, behind API Gateway (HTTP API) | the REST API: pre-signed upload URLs, leases, evidence, dossiers, the rights navigator | A–D |
| `ocr` | worker, fed by SQS | text from a lease: the PDF's text layer first, OCR only for pages without one (ADR-0005), then the clause rules | A |
| `evidence` | worker, fed by SQS | EXIF metadata and the SHA-256 digest of each uploaded file | B |
| `dossier` | worker, fed by SQS | the indexed dispute PDF | C |

ECS stays available through the same kit if the account is ever upgraded and a service needs to
run all the time.

## Consequences

- `realm.toml` gets these four `[[service]]` entries with `runtime = "lambda"`. That's the input
  the AWS bootstrap needs for its image repositories.
- Each worker answers the kit's health contract: invoked with `{"realm":"health"}`, it returns
  `{"ok": true}`.
- A cold start adds latency to the first request after idle. It's measured against the API's NFR,
  and the database's own resume time (ADR-0004) comes on top of it.
- Long documents are split into pages, each page its own SQS message, so no invocation comes near
  15 minutes.
- Schema migrations run as a Lambda function inside the VPC (the `api` image, with another
  handler), started by the pipeline. The database isn't reachable from outside the VPC.
- The spec's "ECS (Fargate)" becomes the documented upgrade path. This ADR is the record of why.
