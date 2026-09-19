# ADR-0003 — Private subnets with no NAT: only the free S3 gateway endpoint

- Status: accepted
- Date: 2026-09-19 · Deciders: Katlego

## Context

The specification asks for strict network isolation: compute in private subnets with no direct
public ingress, and the database in its own subnets that only the application can reach. A
private subnet has no way out to the internet or to AWS's public API endpoints unless something
provides one, and every such way costs money by the hour.

The account is on AWS's free plan: USD 100 of credits, until 2027-02-26 at the latest. That's
**about USD 19 a month for everything**, staging and production together. On-demand prices in
`eu-west-1`, from the AWS Pricing API on 2026-09-19:

| Way out of a private subnet | Cost, per environment and month |
|---|---|
| NAT gateway | $35.04 per AZ, plus $0.048 per GB processed |
| NAT instance (a small EC2 instance doing NAT) | a few dollars, plus $3.65 for its public IPv4 address; its patching is ours |
| Interface endpoints (PrivateLink) | $8.03 per endpoint per AZ. ECS in a private subnet needs at least ECR (two), CloudWatch Logs and Secrets Manager: $32.12 in one AZ |
| S3 gateway endpoint | free |

## Options considered

1. **Do nothing: a NAT gateway**, the textbook design. At $35.04 per environment it's $70 a month
   for two, nearly four times the budget.
2. **A NAT instance.** It's cheap, but it's one more server to patch, it's a single point of
   failure, and it still costs money every hour.
3. **Interface endpoints.** These cost $8 or more per endpoint per AZ, and the list grows with
   every AWS service the code calls.
4. **No way out** (chosen). This works because of ADR-0002: with every service on Lambda, none
   of the usual reasons for a private subnet to reach out apply.

   | What would need to leave the subnet | What happens instead |
   |---|---|
   | pulling the container image | Lambda pulls it, outside our VPC |
   | shipping logs | Lambda ships them, outside our VPC |
   | receiving SQS messages | the event source mapping polls outside our VPC |
   | reading and writing S3 | the S3 gateway endpoint, free |
   | the database password | IAM database authentication: the token is signed locally, with no network call (ADR-0004) |
   | pre-signed URLs | signed locally, with no network call |
   | checking a user's token | API Gateway's JWT authorizer, against Cognito, before the function runs |

## Decision

**No NAT and no interface endpoints.** One VPC per environment, with private subnets in
two AZs (Aurora needs a subnet group in at least two), no internet gateway route from them, and
the free S3 gateway endpoint. The functions that touch the database run in the private subnets.
Their security group allows outbound traffic only to the database's security group and to S3's
prefix list. The database's security group allows inbound traffic only from the functions'.

The whole budget, as decided across ADR-0002 to ADR-0006, for two environments:

| Item | Per month |
|---|---|
| Lambda, API Gateway, SQS, EventBridge, S3 requests | cents at this scale; Lambda within its always-free allowance |
| Aurora while paused | $0 compute; storage $0.11 per GB |
| Aurora while in use, e.g. 20 active hours per environment at 1 ACU | about $5.60 |
| Aurora's managed master secret (Secrets Manager), one per environment | $0.80 |
| KMS: the Terraform state key (from the bootstrap) | $1.00 |
| ECR image storage, CloudWatch logs | about $1 |
| **Total** | **about $9–10**, against a budget of about $19 |

## Consequences

- A function inside the VPC can't call any other AWS API or the internet. That includes Bedrock
  (ADR-0006) and an OpenTelemetry endpoint outside AWS. Functions that need those run outside the
  VPC, and are never given access to the database.
- The kit's OpenTelemetry export can't leave the private subnets. Functions inside the VPC report
  through CloudWatch: logs, and metrics in the embedded metric format, which Lambda ships itself.
- Adding a NAT gateway later is one Terraform change, and a new ADR, if the account is upgraded.
- The AWS Budget (from the bootstrap, `include_credit = false`) is set to $20 a month, so its
  alerts fire before the credits are in danger.
