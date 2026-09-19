# ADR-0007 — Jobs use standard SQS queues, and every worker is idempotent

- Status: proposed
- Date: 2026-09-19 · Deciders: Katlego

## Context

The specification's pipeline puts jobs on an "Amazon SQS FIFO Queue", fed by EventBridge.
Its competency text asks for something weaker: queues backed by dead-letter queues,
"guaranteeing at-least-once processing".

Every job starts as an object in S3, and EventBridge carries the S3 event to the job's queue
(ADR-0003). For a FIFO target, EventBridge's `SqsParameters.MessageGroupId` is **one fixed
string** for the whole rule, not a value taken from the event (EventBridge API reference,
`SqsParameters`, checked 2026-09-19). A FIFO queue processes one message group in order, one
batch at a time. So with FIFO:
- every job of a type would share one group
- the 20 photos of a move-in, or the pages of 3 tenants' leases, would be processed **one at a time**

Nothing in Tokelo needs ordering between jobs. The order that matters, the timeline, comes from
the records' own dates. What does matter is that a job delivered twice does no harm.

## Options considered

1. **Do nothing: FIFO queues with a fixed group per rule.** This matches the specification's
   figure, but it serialises every job type. Its deduplication covers only EventBridge's own
   retries, not a worker that fails halfway.
2. **FIFO queues fed by something that sets the group per tenant,** such as a Lambda between
   EventBridge and SQS. It's ordering nobody needs, at the price of one more function, and a
   function inside the VPC can't call SQS (ADR-0003).
3. **Standard queues, with idempotent workers** (proposed). Each job runs in parallel up to its
   trigger's maximum concurrency, with at-least-once delivery and a dead-letter queue after 3
   failed receives. Each worker keys its work on the S3 object's key and version, so a second
   delivery finds the work done and stops.

## Decision

Proposed: **standard SQS queues, one per job type, each with a dead-letter queue after 3
receives.** Every worker is **idempotent on the S3 object's key and version ID:** a unique
constraint in the database makes a repeated job a no-op.

## Consequences

- `docs/design/infrastructure.md` §4 defines the queues. `PLAN.md` and
  `docs/architecture/containers.md` say "standard queues", not "FIFO".
- REQ-017 and NFR-007 are unchanged. They ask for queues, dead-letter queues and at-least-once
  processing, which this is.
- Every worker's design shows the key it's idempotent on, and a test delivers the same event
  twice.
- The evaluator sees the same competency: jobs decoupled through queues, with dead-letter queues.
  This ADR is the record of why the queues aren't FIFO.
