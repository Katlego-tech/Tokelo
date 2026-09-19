# ADR-0001 — Tokelo runs in eu-west-1 (Ireland)

- Status: proposed
- Date: 2026-09-19 · Deciders: Katlego

## Context

Tokelo's users and landlords are in South Africa, and the data is personal: leases, inspection
photos and dispute records. The original choice of `eu-west-1` rested on Amazon Textract, which
isn't offered in Cape Town (`af-south-1`). Textract is out now: the account is on AWS's free
plan, and Textract refuses it (`SubscriptionRequiredException`), so OCR is open source (ADR-0005).
That reason is gone, so the region is open again.

What the choice still turns on:

| | `eu-west-1` (Ireland) | `af-south-1` (Cape Town) |
|---|---|---|
| Where the data lives | in the EU: a transfer out of South Africa under POPIA section 72 | in South Africa: no cross-border transfer |
| Distance from users | every request crosses to Europe | local |
| Enabled on the account | yes (the default) | yes (checked 2026-09-19) |
| Aurora Serverless v2, per ACU-hour | $0.14 | $0.16 |
| Aurora storage, per GB-month | $0.11 | $0.131 |
| Fargate, per vCPU-hour and GB-hour | $0.04048 and $0.004445 | $0.0546 and $0.006 |
| NAT gateway, per hour | $0.048 | $0.057 |
| Bedrock, Amazon's own Nova models | yes, through EU inference profiles (`eu.amazon.nova-micro-v1:0`, `-lite-`, `-pro-`) | no |
| Bedrock, Anthropic's models | listed | listed, mostly through `global.` inference profiles, which may process a request outside South Africa |

Prices are on-demand, from the AWS Pricing API on 2026-09-19. The credits have to last until the
free plan ends on 2027-02-26: about USD 19 a month (ADR-0003 has the whole budget).

POPIA section 72 allows a transfer when the recipient is bound by law that gives adequate
protection; the GDPR is generally taken to meet that. This is a design constraint for the privacy
notice and the threat model, not legal advice.

## Options considered

1. **Do nothing: stay on `eu-west-1`**, as setup wrote it into `realm.toml` and the three
   `terraform.tfvars`. It's the cheapest of the two, and it's the one region here with Nova models
   (ADR-0006) that need no Marketplace agreement. The cost is the cross-border transfer, which the
   privacy notice must state, and the distance.
2. **Move to `af-south-1`.** The data stays in South Africa and requests stay local. The
   costs: 14–35% higher per hour (Aurora +14%, RDS +24%, Fargate +35%), no Nova models, and Anthropic's models only through a
   Marketplace agreement the free plan may not allow, mostly routed globally. The region can
   change freely until the AWS bootstrap runs (four files); after it, a move means a new bootstrap.

## Decision

Proposed: **`eu-west-1`**. The free plan makes cost the binding constraint, and ADR-0006 may need a
language model that runs without a Marketplace agreement. The transfer out of South Africa is
stated in the privacy notice, and it gets its own entry in the threat model.

## Consequences

- Nothing in the repo changes: `realm.toml` `[deploy] region` and the three `terraform.tfvars`
  already say `eu-west-1`.
- The privacy notice (a requirement in `REQUIREMENTS.md`) must say where the data is stored and
  why, and name the section 72 basis.
- Request latency from South Africa is measured against its NFR once staging runs. Uploads go
  straight to S3 through pre-signed URLs, so the API's round trips are small.
- If a later need outweighs the cost (a user or regulator requiring data in South Africa), a new
  ADR moves the project to `af-south-1` with a new bootstrap.
