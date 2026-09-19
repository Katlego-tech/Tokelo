# `tokelo` — Requirements

**Spec:** [SPEC.md](SPEC.md) · **Tasks:** [TASKS.md](TASKS.md) · **Gates:** [GATES.md](GATES.md)

> SPEC.md tells the story; this file is the list the gate checks. `scripts/realm/realm req-lint`
> checks every entry, and `scripts/realm/realm trace` checks each requirement's links to its tasks,
> commits, tests and releases (ISO/IEC/IEEE 29148; Secret Realm DESIGN.md §7).

---

## How requirements are written here

**Four levels, each with its own ID prefix.** IDs are never reused.

| Level | Prefix | Answers | Parent |
| --- | --- | --- | --- |
| Business | `BR-nnn` | why the system exists | none |
| Stakeholder | `SR-nnn` | what each stakeholder needs from it | a `BR-` (required in the assured tier) |
| Software | `REQ-nnn` | what the software shall do | an `SR-` or a `BR-` (always required) |
| Quality (ISO/IEC 25010) | `NFR-nnn` | how well, as a measured target | any level (required in the assured tier) |

**States:** proposed → approved → implemented → verified → released → deprecated → retired, or
withdrawn. A requirement is **approved** only when:
- its quality checklist ticks all nine characteristics: unambiguous, necessary, feasible,
  verifiable, singular, implementation-free, correct, complete, consistent
- a task names it (`Req:` in TASKS.md)
- a test names it, written first

`implemented` also needs one of its tasks done; `released` needs a release record in
`docs/releases/` that lists it.

**How a test names its requirements** (the trace reads all three):
- **Python:** `@pytest.mark.req("REQ-012")`. Register the marker once in your pytest
  configuration: `markers = ["req(*ids): the requirements this test verifies"]`.
- **JS/TS:** the test title starts with the IDs: `it("[REQ-012] refuses a launch into a full world", …)`.
- **Anything else** (k6 scripts, shell tests): a comment line `req: NFR-003`, in a file under a
  `tests/`, `e2e/`, `perf/` or similar folder.

**Verify by** is one of `test`, `analysis`, `inspection` or `demonstration`. It's required on every
`REQ-` and `NFR-`, and in the assured tier on every level, fixed before the requirement is built
(the V-Model's pairing).

### Entry format

```markdown
### REQ-012 — Refuse a launch into a full world
- Level: software · Parent: SR-004 · State: approved
- Statement: When no cell is free, the system shall refuse the launch and reply "no more space".
- Verify by: test (acceptance)
- Quality: unambiguous ✓ necessary ✓ feasible ✓ verifiable ✓ singular ✓ implementation-free ✓
  correct ✓ complete ✓ consistent ✓

### NFR-003 — API latency
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: SR-004 · State: approved
- Target: p95 < 200 ms for GET /api/robots at 50 requests/second
- Verify by: test (performance)
- Measured by: perf/robots.js (k6) in the release pipeline
- Quality: unambiguous ✓ necessary ✓ feasible ✓ verifiable ✓ singular ✓ implementation-free ✓
  correct ✓ complete ✓ consistent ✓
```

An NFR's **Target** needs a bound (`<`, `≤`, at most, within…) on a number with a unit, and it
names the tool that measures it.

---

## Operational concept (OpsCon)

<!-- Who operates the system, where and under what conditions: its users and their roles, the
     environments it runs in, a normal day, a bad day (load peaks, outages), and what "working"
     looks like to each of them. Required once any requirement is approved. -->

**Who uses it, and for what:**

| Role | Who | What they do | What "working" means to them |
|---|---|---|---|
| Tenant | a residential tenant in South Africa, on a phone or a laptop, often on mobile data | uploads a lease and reads its flags; uploads move-in and move-out photos; builds a dossier; asks a rights question | every flag and answer names a section of the law, and nothing is invented; evidence can be shown to be unchanged; the dossier is accepted as organised |
| Operator | Katlego | merges changes, tags releases, watches the budget and incidents | the gate is green on `main`; the AWS cost stays under USD 20 a month; an incident has a record |
| Evaluator | the cloud elective's assessor | reviews the architecture and a demonstration | the four competencies in the specification (§6) are visible in the running system and in these documents |

**Where it runs:** AWS `eu-west-1`, in two environments, staging and production, from one account
on AWS's free plan, which ends on 2027-02-26 (ADR-0001 to ADR-0004). Both are idle most of the
time: the functions cost nothing and the database pauses. Development runs on the operator's
machine. Real tenant documents never go into the repository.

**A normal day:** a tenant signs in and uploads a lease. The file goes straight to storage, not
through the API. The flags appear within minutes, each with its plain-language explanation and
its section. Later they upload inspection photos, and each is fingerprinted as it arrives. When a
dispute starts, they pick the lease, the photos and the notices, and download one indexed PDF.

**A bad day:**
- The first request after a quiet spell waits for the database to resume, about 15 seconds
  (ADR-0004). The web app says so rather than looking broken.
- A photo is too dark to read. The tenant is told which page failed; nothing is guessed.
- A job fails three times and goes to its dead-letter queue. The tenant sees the item as
  failed, and the operator is alerted.
- The credits run low. The budget emails the operator at 50%, 80% and 100% of USD 20 a month,
  well before the account is at risk.

**What Tokelo never does:** give legal advice, speak for the tenant, or cite anything outside its
curated sources (the grounding rule, [AGENTS.md](AGENTS.md)).

## Business requirements

### BR-001 — Reduce tenants' disadvantage in tenancy disputes
- Level: business · State: proposed
- Statement: Tokelo shall help South African residential tenants understand their leases against
  the law, keep evidence that holds up, and prepare their case for the Rental Housing Tribunal or
  the Small Claims Court.
- Verify by: demonstration

### BR-002 — Demonstrate the cloud elective's four competencies
- Level: business · State: proposed
- Statement: Tokelo shall demonstrate I/O offloading through pre-signed URLs, event-driven
  decoupling with queues and dead-letter queues, strict network isolation, and cryptographic
  data integrity, as the specification's §6 lists them.
- Verify by: demonstration

### BR-003 — Run within AWS's free plan
- Level: business · State: proposed
- Statement: Tokelo's AWS usage shall be paid for by the free plan's credits until the plan ends
  on 2027-02-26, without moving the account to the paid plan.
- Verify by: analysis

## Stakeholder requirements

### SR-001 — Tenants know which clauses conflict with the law, and why
- Level: stakeholder · Parent: BR-001 · State: proposed
- Statement: A tenant needs to know which clauses of their lease conflict with the curated
  statutes, why in plain language, and which section says so.

### SR-002 — Tenants keep evidence whose integrity they can show
- Level: stakeholder · Parent: BR-001 · State: proposed
- Statement: A tenant needs to keep inspection photos and records, and to show later that each
  is unchanged since it was stored and when it was captured.

### SR-003 — Tenants get a dossier ready to file
- Level: stakeholder · Parent: BR-001 · State: proposed
- Statement: A tenant needs one organised, indexed document of their lease, evidence and
  communications, in time order, for the Rental Housing Tribunal or the Small Claims Court.

### SR-004 — Tenants get grounded answers to everyday questions
- Level: stakeholder · Parent: BR-001 · State: proposed
- Statement: A tenant needs answers to everyday tenancy questions that rest only on the curated
  statutes, and a plain "outside what Tokelo covers" otherwise.

### SR-005 — Tenants' personal data is private and handled as POPIA requires
- Level: stakeholder · Parent: BR-001 · State: proposed
- Statement: A tenant needs their documents seen only by themselves, to know where they're
  stored, and to be able to delete them.

### SR-006 — The evaluator can see each competency at work
- Level: stakeholder · Parent: BR-002 · State: proposed
- Statement: The evaluator needs to see each of the four competencies in the running system, and
  where each is built.

### SR-007 — The operator is warned before the credits are at risk
- Level: stakeholder · Parent: BR-003 · State: proposed
- Statement: The operator needs warning before the spending threatens the credits, and a system
  that costs next to nothing while idle.

## Software requirements

### REQ-001 — Serve a tenant's records to that tenant only
- Level: software · Parent: SR-005 · State: proposed
- Statement: The system shall require a signed-in account for every operation on tenant data,
  and shall return or change a tenant's records only for that tenant.
- Verify by: test (acceptance)

### REQ-002 — Upload files without passing them through the API
- Level: software · Parent: SR-006 · State: proposed
- Statement: When a tenant asks to upload a file, the system shall return a pre-signed URL for
  one object, one content type and a maximum size, and the file's bytes shall go straight to
  storage without passing through the API.
- Verify by: test (integration)

### REQ-003 — Accept leases in the forms tenants have them
- Level: software · Parent: SR-001 · State: proposed
- Statement: The system shall accept a lease as a PDF (digital or scanned) or as JPEG or PNG
  photos of its pages, of at most 20 MB per file and 30 pages, and shall refuse any other file
  with the reason.
- Verify by: test (acceptance)

### REQ-004 — Read every page, and say which it couldn't
- Level: software · Parent: SR-001 · State: proposed
- Statement: The system shall take each page's text from the file itself where the file has it,
  and by OCR otherwise, and shall tell the tenant the number of any page it couldn't read.
- Verify by: test (acceptance)

### REQ-005 — Flag clauses that conflict with the curated statutes
- Level: software · Parent: SR-001 · State: proposed
- Statement: The system shall check every clause against the rule catalogue, and for each clause
  a rule matches, shall show the rule's plain-language explanation and the section it rests on.
- Verify by: test (acceptance)

### REQ-006 — Cite only the curated sources, and never advise
- Level: software · Parent: SR-001 · State: proposed
- Statement: Every explanation and answer the system shows shall cite at least one section, every
  section it cites shall be in the curated source list, and each shall state that it is legal
  information, not legal advice.
- Verify by: test (unit, over the whole rule catalogue and every written answer)

### REQ-007 — Never call a clause lawful
- Level: software · Parent: SR-001 · State: proposed
- Statement: When no rule matches a clause, the system shall say that its checks found no issue,
  and shall never say that the clause is lawful.
- Verify by: test (acceptance)

### REQ-008 — Fingerprint every evidence file as it's stored
- Level: software · Parent: SR-002 · State: proposed
- Statement: For every evidence file, the system shall compute its SHA-256 digest when the file is
  stored, and record it with the time it was stored.
- Verify by: test (integration)

### REQ-009 — Record capture metadata, and never invent it
- Level: software · Parent: SR-002 · State: proposed
- Statement: For each photo, the system shall record the capture time, the device and the GPS
  coordinates from its EXIF metadata where present, and "not recorded" where absent.
- Verify by: test (unit)

### REQ-010 — Show that a file is unchanged
- Level: software · Parent: SR-002 · State: proposed
- Statement: When a tenant asks to verify an evidence file, the system shall recompute its digest
  and report whether it matches the one recorded when the file was stored.
- Verify by: test (acceptance)

### REQ-011 — Keep an append-only audit log
- Level: software · Parent: SR-002 · State: proposed
- Statement: The system shall record every upload, verification, dossier and deletion in an audit
  log that the application can append to but not change or delete from.
- Verify by: test (integration)

### REQ-012 — Accept notices and message exports on the timeline
- Level: software · Parent: SR-003 · State: proposed
- Statement: The system shall accept notices (PDF or photos) and WhatsApp chat exports (.txt) as
  dated entries on a tenant's timeline.
- Verify by: test (acceptance)

### REQ-013 — Compile an indexed dossier
- Level: software · Parent: SR-003 · State: proposed
- Statement: When a tenant asks for a dossier of selected records, the system shall produce one
  PDF with an index, the records in time order, each evidence file's metadata and digest, and the
  sections the lease's flags cite, and shall refuse when nothing is selected.
- Verify by: test (acceptance)

### REQ-014 — Answer within the curated topics, and say when a question is outside them
- Level: software · Parent: SR-004 · State: proposed
- Statement: The system shall answer a question in a curated topic with that topic's written
  answer and its sections. For any other question, it shall say that the question is outside what
  Tokelo covers, and point to the Rental Housing Tribunal.
- Verify by: test (acceptance)

### REQ-015 — Tell tenants where their data lives before they sign up
- Level: software · Parent: SR-005 · State: proposed
- Statement: The system shall show a privacy notice before sign-up that says where the data is
  stored, on what basis it leaves South Africa (POPIA section 72), and how to delete it.
- Verify by: inspection

### REQ-016 — Delete an account and everything in it
- Level: software · Parent: SR-005 · State: proposed
- Statement: When a tenant deletes their account, the system shall delete their files and
  records, and keep only the audit log's entries with the tenant's identity removed.
- Verify by: test (acceptance)

### REQ-017 — Process uploads from queues, with dead-letter queues
- Level: software · Parent: SR-006 · State: proposed
- Statement: The system shall process each upload asynchronously from a queue, move a job that
  fails three times to a dead-letter queue, and show the tenant that item as failed.
- Verify by: test (integration)

### REQ-018 — Keep compute and the database off the internet
- Level: software · Parent: SR-006 · State: proposed
- Statement: The functions that reach the database, and the database itself, shall have no
  route to or from the internet, and the database shall accept connections only from those
  functions.
- Verify by: inspection (the Terraform and the deployed security groups)

### REQ-019 — Email the operator as spending rises
- Level: software · Parent: SR-007 · State: proposed
- Statement: The system shall email the operator when the month's AWS cost, not counting
  credits, reaches 50%, 80% and 100% of the monthly budget, and when the forecast reaches 100%.
- Verify by: inspection (the bootstrap's budget)

## Quality requirements

### NFR-001 — A pre-signed upload URL is quick
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: REQ-002 · State: proposed
- Target: p95 < 500 ms for a pre-signed upload URL at 5 requests/second, with the system warm
- Verify by: test (performance)
- Measured by: perf/upload-url.js (k6) in the release pipeline

### NFR-002 — The first request after a pause still completes
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: SR-007 · State: proposed
- Target: the first API request after at least 15 minutes idle completes within 30 s
- Verify by: test (performance)
- Measured by: perf/first-request.js (k6), run against staging after 15 minutes idle

### NFR-003 — A digital lease's flags appear quickly
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: REQ-005 · State: proposed
- Target: p95 < 2 min from the end of the upload to the flags, for a 10-page digital PDF
- Verify by: test (performance)
- Measured by: tests/e2e/test_lease_timing.py on staging

### NFR-004 — OCR keeps pace with a scanned lease
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: REQ-004 · State: proposed
- Target: p95 < 30 s per scanned page in the `ocr` function
- Verify by: test (performance)
- Measured by: the ADR-0005 measurement, then tests/e2e/test_lease_timing.py on staging

### NFR-005 — OCR reads accurately enough to check clauses
- Characteristic (ISO/IEC 25010): functional suitability · Parent: REQ-004 · State: proposed
- Target: character error rate ≤ 5% on the scanned samples and ≤ 15% on the phone-photo samples
- Verify by: test (accuracy)
- Measured by: tests/ocr/test_accuracy.py over the synthetic sample leases

### NFR-006 — A pre-signed URL expires quickly
- Characteristic (ISO/IEC 25010): security · Parent: REQ-002 · State: proposed
- Target: every pre-signed URL expires within 15 min of being issued
- Verify by: test (unit)
- Measured by: tests/api/test_presign.py

### NFR-007 — Few jobs fail for good
- Characteristic (ISO/IEC 25010): reliability · Parent: REQ-017 · State: proposed
- Target: at most 1% of jobs reach a dead-letter queue over any 7 days
- Verify by: analysis
- Measured by: the queues' CloudWatch metrics, in docs/ops/slo.toml

### NFR-008 — The system costs little while idle, and stays in budget
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: BR-003 · State: proposed
- Target: AWS cost, not counting credits, at most 20 USD per month
- Verify by: analysis
- Measured by: the AWS Budget from the bootstrap (include_credit = false)

### NFR-009 — The web app is accessible
- Characteristic (ISO/IEC 25010): interaction capability · Parent: SR-001 · State: proposed
- Target: at most 0 errors at WCAG 2.1 AA on every page pa11y checks
- Verify by: test (accessibility)
- Measured by: pa11y in the release pipeline
