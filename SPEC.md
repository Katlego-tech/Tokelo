# `Tokelo` — Specification (the WHAT)

**Related:** [PLAN.md](PLAN.md) (the HOW) · [TASKS.md](TASKS.md) (the backlog) ·
[REQUIREMENTS.md](REQUIREMENTS.md) (what the gate checks) · the source: *Tokelo: Cloud-Native
Tenant Protection and Dispute Resolution Engine*, v1.0

---

## Overview

Tokelo is a web app for South African residential tenants in tenancy disputes. A tenant uploads
their lease and sees which clauses conflict with the Rental Housing Act, the Consumer Protection
Act and the PIE Act, each explained in plain language with its section. They keep move-in and
move-out photos that can be shown to be unchanged, and download one indexed dossier for the Rental
Housing Tribunal or the Small Claims Court.

It runs on AWS, event-driven and serverless (ADR-0001 to ADR-0006).

### Goals

- Flag the lease clauses that conflict with the curated statutes, and explain each in plain
  language, with its section.
- Keep inspection evidence tamper-evident: a SHA-256 digest when each file is stored, its
  capture metadata, and a check that it's unchanged.
- Compile the tenant's lease, evidence and communications into one indexed, time-ordered PDF.
- Answer everyday tenancy questions within curated topics, citing the section.
- Keep each tenant's data private, and handle it as POPIA requires.

### Non-goals

- **Legal advice,** representing a tenant, or filing anything on their behalf. Tokelo gives legal
  information and says so.
- **Anything outside the curated sources:** other statutes, regulations or case law (the
  grounding rule).
- **Landlord accounts** or features for landlords and agents.
- **A native mobile app.** The web app works on phones.
- **A generated, conversational chatbot** in phases 1–5 (ADR-0006).
- Payments and e-signatures.
- **Any language but English,** in the interface or in the leases Tokelo reads (ADR-0009).

---

## Actors

### The tenant

1. Signs up after reading the privacy notice, and signs in.
2. Uploads a lease, as a PDF or photos, and waits a few minutes.
3. Reads the flagged clauses: each with its explanation and section, and "no issue found by
   these checks" for the rest.
4. Uploads inspection photos at move-in and move-out, and notices and WhatsApp exports as they
   arrive. Each gets its digest.
5. When a dispute starts, selects records and downloads the dossier. They can verify any file
   against its digest.
6. Asks a question, and gets a written answer with its section, or a plain "outside what Tokelo
   covers".

They judge success by whether the flags and answers are right and cite the law, and whether the
dossier is ready to hand in.

### The evaluator (the cloud elective)

The specification's §6 is the rubric. Each competency must be visible in the running system and
traceable to where it's built:

| Competency | Where it's built |
|---|---|
| I/O offloading through pre-signed S3 URLs | REQ-002, NFR-001, NFR-006 |
| Resilient, event-driven decoupling with SQS and dead-letter queues | REQ-017, NFR-007 |
| Strict network isolation: private subnets, and a database only the application reaches | REQ-018, ADR-0003 |
| Cryptographic data integrity: SHA-256 verification and an immutable audit log | REQ-008, REQ-010, REQ-011 |

### The operator

Releases through the kit's pipeline, and watches the budget (REQ-019) and incidents.

---

## User stories

### US1 — Check a lease against the statutes (P1)

**As a** tenant, **I want** my lease checked against the law, **so that** I know which clauses I
don't have to accept, and why.

```
Scenario: a digital lease with an unlawful lock-out clause
  Given a digital PDF lease whose clause 12 lets the landlord change the locks for late rent
  When  the tenant uploads it
  Then  clause 12 is flagged, with a plain-language explanation citing the PIE Act,
        and the page says this is legal information, not legal advice
```

- **Scenario: a scanned lease.** Given a scanned PDF, when it's uploaded, then its text is read by
  OCR and its clauses are checked like a digital one's.
- **Scenario: a page that can't be read.** Given a photo too dark to read, when it's uploaded,
  then the tenant is told that page 3 couldn't be read. Nothing is guessed for it.
- **Scenario: nothing matches.** Given a clause no rule matches, then it reads "no issue found by
  these checks", never "lawful".
- **Scenario: the wrong file.** Given a 40 MB file or a .docx, then it's refused with the reason.

**Acceptance criteria:**
- [ ] every flag names a section in the curated list (REQ-005, REQ-006)
- [ ] a 10-page digital lease's flags appear within 2 minutes, p95 (NFR-003)

### US2 — Keep tamper-evident inspection evidence (P1)

**As a** tenant, **I want** my inspection photos kept in a way I can prove, **so that** a deposit
can't be withheld on my word against the landlord's.

- **Scenario: photos at move-in.** Given 20 photos, when they're uploaded, then each gets its
  SHA-256 digest, its time of storage, and its EXIF capture time, device and location.
- **Scenario: a photo without metadata.** Then its capture fields read "not recorded". Nothing is
  inferred.
- **Scenario: proving a file is unchanged.** Given a stored photo, when the tenant verifies it,
  then Tokelo recomputes the digest and says it matches.
- **Scenario: a changed file.** Given a file whose bytes differ from what was stored, then the
  verification says it doesn't match.

**Acceptance criteria:**
- [ ] every upload, verification and dossier is in the append-only audit log (REQ-011)

### US3 — Compile a dispute dossier (P2)

**As a** tenant, **I want** one organised document of my case, **so that** the Tribunal or the
court can follow it.

- **Scenario: a dossier.** Given the lease, 20 photos, 2 notices and a WhatsApp export, when the
  tenant selects them, then one PDF arrives: an index, the records in time order, each photo's
  metadata and digest, and the sections the lease's flags cite.
- **Scenario: nothing selected.** Then Tokelo refuses and says why.

### US4 — Ask a rights question (P3)

**As a** tenant, **I want** answers to everyday questions, **so that** I know where I stand
without a lawyer for every small thing.

- **Scenario: a curated topic.** Given "Can my landlord cut the water because I'm late?", then
  the answer cites the Rental Housing Act and the PIE Act, and says it's legal information.
- **Scenario: outside the topics.** Given "Can I sublet on Airbnb?", when it isn't curated, then
  Tokelo says so plainly and points to the Rental Housing Tribunal. It never answers from
  anything else, and never cites case law.

---

## Acceptance criteria (system-level)

- [ ] Every explanation and answer cites a section in the curated list; a test holds the whole
      rule catalogue and every written answer to it (REQ-006).
- [ ] A tenant sees only their own records (REQ-001).
- [ ] Each of the four competencies can be demonstrated (the evaluator's table above).
- [ ] The privacy notice says where the data lives, and why that's allowed (REQ-015).
- [ ] The AWS cost stays within the budget, and the budget's alerts work (NFR-008, REQ-019).
