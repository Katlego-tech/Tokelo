# ADR-0006 — No language model in phases 1–5: explanations and answers are written, not generated

- Status: accepted
- Date: 2026-09-19 · Deciders: Katlego

## Context

Two modules could use a language model:

- **Module A's plain-language explanations:** the specification says it "generates conversational
  translations" of each clause.
- **Module D, the statutory rights navigator:** it answers everyday tenancy questions by
  "referencing relevant statutory provisions and case law precedents".

Tokelo's grounding rule is the one thing it must never get wrong: never state, cite or paraphrase
a statute, section, time limit or case that isn't in its curated legal sources (the Rental
Housing Act 50 of 1999; the Consumer Protection Act 68 of 2008, sections 14 and 48; the PIE Act
19 of 1998), and never present legal information as legal advice. A generated answer can invent a
section or a deadline that reads as true. Case law isn't among the curated sources at all.

What's available on this account (checked 2026-09-18 and 2026-09-19, with no model invoked):

- **Amazon's Nova models,** through EU inference profiles in `eu-west-1`. They need no Marketplace
  agreement, but whether the free plan allows invoking them is unverified.
- **Anthropic's models,** listed and authorized, but their Marketplace agreement is
  `NOT_AVAILABLE`. The free plan excludes "certain AWS Marketplace offers", so they may be closed
  to it.
- Either way, a function calling Bedrock runs outside the VPC (ADR-0003).

## Options considered

1. **Do nothing: no model** (chosen for phases 1–5).
   - **Module A:** each rule in the rules engine carries its own explanation, written once from
     the curated source it enforces, with that source's section.
   - **Module D:** answers come from a curated set of question topics, each written from and
     citing the curated sources.

   Every word is reviewable and testable, and it costs nothing.
2. **Nova (Micro or Lite) through an EU inference profile,** with its input limited to passages
   retrieved from the curated sources. A validator rejects any answer that cites a section outside
   them, falling back to option 1's text. It sounds more natural, but its correctness is only as
   good as the validator. It costs per token, and it needs one test invocation to prove the free
   plan allows it.
3. **Anthropic's models (Claude Haiku 4.5) through Bedrock.** These need the Marketplace
   agreement, which may not be open to the free plan.
4. **A model outside AWS.** That's another account, another bill, and tenant data leaving AWS.
   Rejected.

## Decision

**Option 1 for phases 1–5.** Explanations and navigator answers are written by hand from
the curated sources, and each cites its section. A language model can be added later through a
new ADR, once:

- the written answers exist to test it against, and
- one test invocation of Nova, with the user's go-ahead because it spends credits, shows the free
  plan allows it.

## Consequences

- The grounding rule is enforceable by tests: every explanation and answer names a section, and a
  test checks that section is in the curated set.
- Module D's scope is the curated topics, and it says plainly when a question is outside them.
  There's no case law, because none is curated.
- Writing the explanations and answers is real work in phases 3 and 4. `TASKS.md` gets tasks for
  it.
- No Bedrock cost and no Marketplace question in phases 1–5. ADR-0003's budget has no line for it.
