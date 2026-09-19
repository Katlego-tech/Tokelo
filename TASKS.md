# `Tokelo` — Tasks

**Plan:** [PLAN.md](PLAN.md) · **Spec:** [SPEC.md](SPEC.md) · **Designs:** [docs/design/](docs/design/)

> One of the three shared-state files (with [AGENTS.md](AGENTS.md) and [STATUS.md](STATUS.md)).
> **One writer per task** — claim it in STATUS.md before you start.

---

## How tasks are written here

A task is a **contract**, not a reminder. The person writing it and the person (or AI) building it
are usually not the same, and the builder will implement *exactly* what the task specifies — so a
task that under-specifies gets you something plausible-looking and wrong: the right file with a
`TODO` in it, a component that renders *a* screen rather than *the* screen, a function with the
agreed name and a stubbed body.

**The task is under-specified if a competent implementer who read nothing else could build
something structurally different from what you intend.** When that's true, the fix is not a longer
sentence — it's a design doc ([docs/design-documentation.md](docs/design-documentation.md)) and a
reference to it.

### Anatomy

```
- [ ] T0nn [P] [US1] <imperative one-line summary>
      Design:  docs/design/<lane>.md §<section>        <- the structure to build to
      Files:   <paths this task creates or changes>
      Contract:<exact signature / schema / props — or the design §ref that has it>
      Verify:  <the command or check that proves it works>
      Done:    <the observable end state, in the user's or caller's terms>
```

| Field | Required when | Why it's there |
| --- | --- | --- |
| **Design** | the task creates structure (types, services, screens, flows) | gives the implementer a diagram to build to instead of a guess |
| **Files** | always, unless genuinely unknowable | stops two lanes colliding; makes "did it touch the right thing" reviewable |
| **Contract** | anything another lane or task consumes | lets parallel lanes compose instead of each inventing an interface |
| **Verify** | always | a task with no check is a task nobody can close honestly |
| **Done** | always | phrased as an outcome, so "the file exists" can't pass for "it works" |

### Rules

1. **No placeholder deliverables.** A task may not be closed with `TODO`, `FIXME`, `pass`,
   `NotImplementedError`, an empty component, hard-coded fake data standing in for a real call, or
   a function that returns a constant to make a test green. If the real thing can't be built yet,
   the task is **blocked**, not done — say so in STATUS.md and name what unblocks it.
   *The one exception:* a deliberately stubbed dependency that the task text names as a stub, with
   a follow-up task ID already written for replacing it.
2. **Every task is a vertical slice.** "Create the module skeleton" is not a task; "parse a
   pain.001 payload into a `Transfer` and reject a malformed one" is. Scaffolding is part of the
   first behavioural task, not a task of its own.
3. **Sized to one sitting.** If a task can't be finished and verified in one working session,
   split it. Long tasks are where placeholders come from — the implementer runs out of room and
   leaves a marker.
4. **Tests first, and the test must fail for the right reason.** A test that passes against an
   empty implementation is not a test. Write it, watch it fail, then implement.
5. **UI tasks name their visual reference by path.** Never "build the dashboard" — always "build
   the dashboard in `<path>/screen.png`, matching layout, tokens and copy". See
   [docs/design-documentation.md](docs/design-documentation.md) § UI is a special case.
6. **One story label per task.** If a task serves two user stories, it's two tasks.
7. **`[P]` means genuinely parallel** — disjoint files *and* no unmet dependency. If two `[P]`
   siblings both touch the same file, one of them is mislabelled.

### Good vs. bad

> ❌ `- [ ] T014 [US2] Build the compliance dashboard`
>
> Produces: *a* dashboard. Some cards, some invented metrics, a chart library nobody chose.
>
> ✅
> ```
> - [ ] T014 [US2] Build the Compliance Health Dashboard screen
>       Design:  docs/design/compliance-ui.md §3 (component tree), §2 (reference)
>       Files:   apps/web/src/pages/ComplianceDashboard.tsx, apps/web/src/components/compliance/*
>       Contract:consumes GET /api/compliance/health -> ComplianceHealth (docs/design/compliance-ui.md §6)
>       Verify:  npm test -w apps/web && npm run dev, compare against legacy/mockups/compliance/screen.png
>       Done:    all six modules from the mockup render with live data from the endpoint; no
>                hard-coded metric values remain in the component
> ```

---

## Legend

Format: `[ID] [P?] [Story] Description`

- **[ID]** — task identifier `Tnnn`, monotonically increasing, never reused.
- **[P]** — parallelizable: touches different files from its siblings and has no unmet dependency.
- **[Story]** — the label the task serves (`US1`–`USn`, `SET` setup, `FND` foundational,
  `DSN` design/documentation, `POL` polish).
- Commit format: `feat(scope): Tnnn short description` (e.g. `feat(audio): T041 add HIP whisper loader`).

Each user-story phase is ordered **Design → Tests FIRST (must FAIL) → Implementation → Checkpoint**.

---

## Phase 0 — Design

> Merged before Phase 2 implementation starts. Cheap, markdown-only, and the thing that decides
> whether everything after it is built to a shape or to a guess.

- [x] T001 [DSN] Design the domain model: the core entities and their relations
      Req:     none — design documentation
      Files:   docs/design/domain-model.md
      Verify:  `scripts/realm/realm design-check` passes; the class diagram names every entity
               REQUIREMENTS.md uses (tenant, lease, page, clause, rule, flag, evidence file,
               timeline entry, dossier, audit entry, topic)
      Done:    each entity has its fields, keys and owner, and the audit log's append-only rule
- [x] T002 [P] [DSN] Design the `api` lane: endpoints, authorization, pre-signed URLs, job requests
      Req:     none — design documentation
      Files:   docs/design/api.md
      Verify:  `design-check` passes, with the lane's STRIDE threats each mitigated
      Done:    every endpoint has its request, response and errors; the sequence from upload to job
               is drawn; how a job request becomes an S3 object is specified (ADR-0003)
- [x] T003 [DSN] Decide the architecture: ADR-0001 to ADR-0006 in docs/adr/
      Req:     none — design documentation (the decisions the requirements and designs rest on)
      Files:   docs/adr/0001-region.md … docs/adr/0006-language-model.md
      Verify:  `scripts/realm/realm adr-check` passes, and each ADR's Status is Katlego's decision
      Done:    the region, the services and their runtimes, the network, the database, the OCR
               engine and the language model are each accepted or rejected, so the AWS bootstrap
               and the design docs can start
- [x] T004 [DSN] Write the specification, the plan, the operational concept, the requirements (proposed) and C4 levels 1–2
      Req:     none — design documentation (the requirements themselves are its output)
      Files:   SPEC.md, PLAN.md, REQUIREMENTS.md, docs/architecture/context.md, docs/architecture/containers.md
      Verify:  `scripts/realm/realm req-lint` and `design-check` pass; Katlego reviews the PR
      Done:    everything the Concept gate reads exists. The gate passes once the business and
               stakeholder requirements are approved, through approved requirements beneath them
               that tasks and tests name
- [x] T055 [DSN] Plan the build: TASKS.md by phase, every task naming its requirements
      Req:     none — design documentation (the plan of work)
      Files:   TASKS.md, PLAN.md (the build phases)
      Verify:  `scripts/realm/realm trace` has 0 broken links, and every REQ- and NFR- is named by at least one task
      Done:    phases 0–7 from design to release, each ending at a demoable checkpoint
- [x] T005 [P] [DSN] Design the infrastructure: VPC, subnets, security groups, S3, events, queues, Aurora, Cognito
      Req:     none — design documentation
      Files:   docs/design/infrastructure.md
      Verify:  `design-check` passes; the deployment diagram shows no route to the internet from
               the private subnets (ADR-0003)
      Done:    every resource T019–T021 create is named, with its settings and its cost line
- [x] T006 [P] [DSN] Design the `ocr` lane: text layer, OCR, clause splitting, the rule catalogue
      Req:     none — design documentation
      Files:   docs/design/ocr.md
      Verify:  `design-check` passes, with STRIDE threats (a malicious PDF included)
      Done:    the rule catalogue's file format is fixed: a match, an explanation and a section
               per rule; the page-per-message fan-out is drawn
- [x] T007 [P] [DSN] Design the `evidence` lane: digests, EXIF, verification, the audit log
      Req:     none — design documentation
      Files:   docs/design/evidence.md
      Verify:  `design-check` passes, with STRIDE threats
      Done:    when the digest is taken and how verification reads the file are drawn
- [x] T008 [P] [DSN] Design the `dossier` lane: the PDF's structure and the timeline
      Req:     none — design documentation
      Files:   docs/design/dossier.md
      Verify:  `design-check` passes, with STRIDE threats
      Done:    the PDF's sections and the timeline's ordering rules are fixed; the PDF library is chosen
- [ ] T009 [P] [DSN] Design the navigator: the curated topics and how a question finds one
      Req:     none — design documentation
      Files:   docs/design/navigator.md
      Verify:  `design-check` passes, with STRIDE threats
      Done:    the topic file format, the matching rule and the "outside what Tokelo covers" reply are fixed
- [ ] T010 [P] [DSN] Design the web app: screens, flows, the privacy notice, the wait while the database resumes
      Req:     none — design documentation
      Files:   docs/design/web.md, docs/design/web/*.svg (one reference per screen)
      Verify:  `design-check` passes, with STRIDE threats; each screen T028, T036, T041, T045 and
               T048 build has its reference image
      Done:    the toolchain is pinned; how the static site is released, and how the kit's pa11y
               check reaches it, is decided

**Checkpoint:** every lane in Phase 2+ has a merged design doc; `docs/design/README.md` indexes them.

---

## Phase 1 — Setup

- [ ] T011 [SET] Create the Python project with its first behaviour: the `api` answers its health check
      Req:     none — setup (the gate's first project manifest)
      Design:  docs/design/api.md
      Files:   pyproject.toml, src/tokelo/api/handler.py, services/api/Dockerfile, tests/unit/test_health.py
      Contract:GET /health → 200 {"ok": true}
      Verify:  the test is written first and fails; then `bash scripts/gate.sh` passes, across 1 project
      Done:    ruff, pyright and pytest run in the gate, with the `req` marker registered. The image
               builds from Lambda's Python 3.14 base, pinned by digest. A new branch's first push
               no longer trips the no-manifest rule
- [ ] T012 [SET] Give the three workers their health answers
      Req:     none — setup (the kit's worker health contract)
      Files:   src/tokelo/{ocr,evidence,dossier}/handler.py, services/{ocr,evidence,dossier}/Dockerfile, tests/unit/test_health.py
      Contract:invoked with {"realm":"health"} → {"ok": true}
      Verify:  the tests are written first and fail; then `pytest tests/unit/test_health.py` passes
      Done:    all four images build
- [ ] T013 [SET] Declare the four services in realm.toml
      Req:     none — deployment configuration (ADR-0002)
      Files:   realm.toml
      Verify:  `scripts/realm/realm release services` prints four rows: `api` web with `ui = true`
               (ADR-0010), the rest workers, all `runtime = "lambda"`
      Done:    `realm release names` prints api, ocr, evidence, dossier: the bootstrap's input
- [ ] T014 [P] [SET] Create the web app skeleton, built and tested in the gate
      Req:     none — setup
      Design:  docs/design/web.md
      Files:   web/ (package.json and its lock file, the pinned toolchain), services/api/Dockerfile (a Node
               stage), src/tokelo/api/static.py
      Verify:  `bash scripts/gate.sh` lints, tests and builds web/, across 2 projects
      Done:    an empty app builds, and the `api` image serves it at `/` with its security headers and
               `/config.json` (ADR-0010); no page is built yet (T027 builds the first)
- [ ] T015 [SET] Require the `gate` check on `main` (branch protection, step 2)
      Req:     none — repository settings
      Verify:  `gh api repos/Katlego-tech/Tokelo/branches/main/protection --jq .required_status_checks.contexts` prints ["gate"]
      Done:    a PR can't merge with a red gate. It waits for T011, so no push run is red for want of a manifest
- [ ] T016 [SET] Bootstrap AWS: the state bucket, the roles, the image repositories and the budget (with Katlego's go-ahead)
      Req:     REQ-019, NFR-008
      Files:   infra/*/backend.hcl, infra/bootstrap/terraform.tfvars, realm.toml ([deploy] registry)
      Verify:  Katlego runs `aws login --profile tokelo` and `TF_VAR_budget_email=… bash scripts/realm/aws-bootstrap.sh`.
               `gh variable list` shows AWS_REGION and the four role variables;
               `aws budgets describe-budgets` shows USD 20 with credits excluded;
               `aws ecr describe-repositories` lists tokelo/api, /ocr, /evidence, /dossier
      Done:    the files it writes are merged through a PR; the account is still on the free plan
- [ ] T017 [SET] Seed the images: tag v0.0.0 (with Katlego's go-ahead)
      Req:     none — the kit's seed (the kit's DESIGN.md §14)
      Verify:  the release workflow publishes and stops; `aws ecr describe-images` shows v0.0.0 in each repository
      Done:    Terraform can create the functions from the seed images
- [ ] T018 [SET] Create staging's network and database (with Katlego's go-ahead)
      Req:     REQ-018, NFR-008
      Design:  docs/design/infrastructure.md
      Files:   infra/envs/staging/*.tf
      Verify:  the PR's plan shows no NAT, no internet gateway and Aurora at 0–2 ACU; after the merge
               applies it, the private subnets' route tables have no 0.0.0.0/0 route and
               `aws rds describe-db-clusters` shows MinCapacity 0 and IAM authentication on
      Done:    the database pauses when idle
- [ ] T019 [SET] Create staging's documents bucket, event rules and queues (with Katlego's go-ahead)
      Req:     REQ-002, REQ-017
      Design:  docs/design/infrastructure.md
      Files:   infra/envs/staging/*.tf
      Verify:  the plan shows the bucket private (Block Public Access, SSE-KMS with the AWS-managed key,
               versioning) and one SQS FIFO queue per job type, each with a dead-letter queue after 3 receives
      Done:    applied to staging
- [ ] T020 [SET] Create staging's user pool, HTTP API and the four functions (with Katlego's go-ahead)
      Req:     REQ-001
      Design:  docs/design/infrastructure.md, docs/design/api.md
      Files:   infra/envs/staging/*.tf, realm.toml (staging_url)
      Verify:  `curl https://<staging API>/health` returns 200; the three database-facing functions are in the private subnets
      Done:    the functions run the v0.0.0 images; realm.toml has the api's staging URL
- [ ] T021 [SET] Release v0.1.0 to staging through the pipeline
      Req:     none — the release pipeline
      Verify:  the release workflow deploys by digest, the smoke checks pass for all four services,
               and it opens "release: v0.1.0 staged"
      Done:    staging runs signed images built from main

**Checkpoint:** four healthy services on staging, deployed by the pipeline; the gate is required on `main`.

---

## Phase 2 — Foundational (blocking)

- [ ] T022 [FND] Curate the legal sources: the sections the rules and answers may cite
      Req:     REQ-006
      Files:   docs/legal/*.md, src/tokelo/core/sources.py, tests/unit/test_sources.py
      Contract:sources.section(id) → text and official source; sources.ids() → the curated set
      Verify:  the test is written first and fails; then every ID is unique, and each section has
               its text and where it's from
      Done:    the Rental Housing Act 50 of 1999, the Consumer Protection Act 68 of 2008 (sections 14
               and 48) and the PIE Act 19 of 1998, as far as the rules and topics need them
- [ ] T023 [FND] Create the schema, and keep the audit log append-only
      Req:     REQ-011
      Design:  docs/design/domain-model.md
      Files:   infra/db/migrations/0001_*.sql, scripts/migrate.py, .github/workflows/realm-infra.yml, tests/integration/test_schema.py
      Verify:  the test is written first and fails; then, against PostgreSQL 16 in Docker, the
               application role can INSERT into the audit log but UPDATE and DELETE are refused
      Done:    `realm-infra`'s apply job runs the migrations through the RDS Data API after `terraform
               apply` (ADR-0008), and the functions connect only as the application user
- [ ] T024 [FND] Serve each tenant only their own records
      Req:     REQ-001
      Design:  docs/design/api.md
      Files:   src/tokelo/api/auth.py, tests/api/test_authz.py
      Verify:  the test is written first and fails; then a tenant asking for another's lease gets 404
      Done:    every query is scoped to the tenant in the token's claims
- [ ] T025 [FND] Issue pre-signed upload URLs
      Req:     REQ-002, NFR-006
      Design:  docs/design/api.md
      Files:   src/tokelo/api/uploads.py, tests/api/test_presign.py
      Contract:POST /api/uploads {kind, content_type, size} → {url, key, expires_at} (docs/design/api.md)
      Verify:  the test is written first and fails; then the URL allows one key, one content type
               and at most the stated size, and expires within 15 minutes
      Done:    the API never receives a file's bytes
- [ ] T026 [FND] Carry jobs from S3 through the queues, and fail them into dead-letter queues
      Req:     REQ-017
      Design:  docs/design/infrastructure.md, docs/design/api.md
      Files:   src/tokelo/core/jobs.py, tests/integration/test_job_spine.py
      Verify:  the test is written first and fails; then, on staging, an object in S3 reaches its
               worker, and a job that fails three times lands in the dead-letter queue with its item marked failed
      Done:    the tenant sees a failed item as failed
- [ ] T027 [FND] Web: sign up after the privacy notice, sign in, and upload a file
      Req:     REQ-015, REQ-001, NFR-009
      Design:  docs/design/web.md, docs/design/web/sign-up.svg, docs/design/web/upload.svg
      Files:   web/src/…
      Verify:  the tests are written first and fail; then axe reports 0 violations, and the notice
               states where data is stored and the POPIA section 72 basis
      Done:    a signed-in tenant uploads a file straight to S3 on staging

**Checkpoint:** a signed-in tenant uploads a file straight to storage, and its job reaches a worker on staging.

---

## Phase 3 — US1 Check a lease against the statutes

- [ ] T028 [US1] Build the synthetic sample leases and the OCR accuracy test (ADR-0009's measurement)
      Req:     NFR-005, NFR-004
      Design:  docs/design/ocr.md
      Files:   tests/fixtures/leases/ (English only: digital, scanned, phone photo, each with its known text), tests/ocr/test_accuracy.py
      Verify:  the test runs and fails because no OCR exists yet
      Done:    it measures the character error rate and the time per page for each form
- [ ] T029 [US1] Read every page, and say which couldn't be read
      Req:     REQ-004, NFR-004, NFR-005
      Design:  docs/design/ocr.md
      Files:   src/tokelo/ocr/pages.py, services/ocr/Dockerfile, tests/ocr/test_pages.py
      Verify:  T028's test passes: character error rate ≤ 5% on scans and ≤ 15% on photos, and
               under 30 s a page; an unreadable page is reported by its number
      Done:    the text layer is used where present. If Tesseract misses NFR-005, the task is
               blocked, and a new ADR proposes PaddleOCR
- [ ] T030 [US1] Accept or refuse a lease file
      Req:     REQ-003
      Design:  docs/design/api.md, docs/design/ocr.md
      Files:   src/tokelo/api/uploads.py, src/tokelo/ocr/intake.py, tests/api/test_lease_intake.py
      Verify:  the tests are written first and fail; then PDF, JPEG and PNG of at most 20 MB and 30
               pages are accepted, and anything else is refused with its reason
      Done:    checked when the URL is requested and again in the worker
- [ ] T031 [US1] Split a lease's text into clauses
      Req:     REQ-005
      Design:  docs/design/ocr.md
      Files:   src/tokelo/ocr/clauses.py, tests/ocr/test_clauses.py
      Verify:  the tests are written first and fail; then the sample leases split into their numbered clauses
      Done:    each clause keeps its number, its page and its text
- [ ] T032 [US1] Write the rule catalogue, each rule with its explanation and section
      Req:     REQ-005, REQ-006
      Design:  docs/design/ocr.md
      Files:   src/tokelo/ocr/rules/*, tests/unit/test_rules.py
      Verify:  the tests are written first and fail; then each rule flags its example and not its
               counter-example, and every rule cites a section from T022's curated set
      Done:    rules for joint inspections, the deposit's interest and refund times, unlawful
               dispossession, fixed-term cancellation, unfair terms and waivers, and eviction only by court order
- [ ] T033 [US1] Flag the clauses, and never call one lawful
      Req:     REQ-005, REQ-007
      Design:  docs/design/ocr.md
      Files:   src/tokelo/ocr/flags.py, tests/ocr/test_flags.py
      Verify:  the tests are written first and fail; then matching clauses are flagged with their
               rule, and the rest read "no issue found by these checks"
      Done:    the flags are stored against the lease
- [ ] T034 [US1] Serve a lease's flags
      Req:     REQ-005, REQ-006, REQ-007
      Design:  docs/design/api.md
      Files:   src/tokelo/api/leases.py, tests/api/test_flags.py
      Contract:GET /api/leases/{id}/flags → the flags, each with its explanation, section and the legal-information notice
      Verify:  the tests are written first and fail; then they pass
      Done:    only the lease's own tenant can read them (REQ-001)
- [ ] T035 [US1] Web: upload a lease and read its flags
      Req:     REQ-003, REQ-005, NFR-009
      Design:  docs/design/web.md, docs/design/web/lease.svg
      Files:   web/src/…
      Verify:  the tests are written first and fail; then axe reports 0 violations on the screen
      Done:    matches the reference, with live data from staging
- [ ] T036 [US1] Time a lease end to end on staging
      Req:     NFR-003, NFR-004
      Files:   tests/e2e/test_lease_timing.py
      Verify:  a 10-page digital lease's flags arrive in under 2 minutes, p95, and a scanned page takes under 30 s
      Done:    it runs against staging in the release pipeline

**Checkpoint:** US1 is independently demoable on staging.

---

## Phase 4 — US2 Keep tamper-evident inspection evidence

- [ ] T037 [US2] Fingerprint each evidence file as it's stored
      Req:     REQ-008, REQ-011
      Design:  docs/design/evidence.md
      Files:   src/tokelo/evidence/digest.py, tests/evidence/test_digest.py
      Verify:  the tests are written first and fail; then each file's SHA-256 and time of storage are
               recorded, with an audit entry
      Done:    the `evidence` worker takes the digest from the stored object, not from the client
- [ ] T038 [US2] Record each photo's capture metadata, and never invent it
      Req:     REQ-009
      Design:  docs/design/evidence.md
      Files:   src/tokelo/evidence/exif.py, tests/evidence/test_exif.py
      Verify:  the tests are written first and fail; then capture time, device and GPS are read
               where present, and "not recorded" where absent
      Done:    stored with the file's record
- [ ] T039 [US2] Verify that a file is unchanged
      Req:     REQ-010, REQ-011
      Design:  docs/design/evidence.md, docs/design/api.md
      Files:   src/tokelo/api/evidence.py, tests/api/test_verify.py
      Contract:POST /api/evidence/{id}/verify → {matches, recorded_digest, computed_digest}
      Verify:  the tests are written first and fail; then an unchanged file matches and a changed one doesn't
      Done:    each verification is an audit entry
- [ ] T040 [US2] Web: upload evidence, see its metadata, and verify it
      Req:     REQ-008, REQ-009, REQ-010, NFR-009
      Design:  docs/design/web.md, docs/design/web/evidence.svg
      Files:   web/src/…
      Verify:  the tests are written first and fail; then axe reports 0 violations on the screen
      Done:    matches the reference, with live data from staging

**Checkpoint:** US2 is independently demoable on staging.

---

## Phase 5 — US3 Compile a dispute dossier

- [ ] T041 [US3] Put notices and WhatsApp exports on the timeline
      Req:     REQ-012
      Design:  docs/design/dossier.md
      Files:   src/tokelo/dossier/timeline.py, tests/dossier/test_timeline.py, tests/fixtures/timeline/
      Verify:  the tests are written first and fail; then a synthetic WhatsApp .txt export and
               notices become dated entries
      Done:    entries sort into time order
- [ ] T042 [US3] Request a dossier, and refuse an empty one
      Req:     REQ-013
      Design:  docs/design/api.md
      Files:   src/tokelo/api/dossiers.py, tests/api/test_dossier_request.py
      Contract:POST /api/dossiers {record_ids} → 202 {dossier_id}; the job request is an object in S3 (ADR-0003)
      Verify:  the tests are written first and fail; then an empty selection, or one of more than
               150 documents, is refused with its reason
      Done:    the request reaches the `dossier` queue
- [ ] T043 [US3] Compile the dossier PDF
      Req:     REQ-013, REQ-011
      Design:  docs/design/dossier.md
      Files:   src/tokelo/dossier/pdf.py, src/tokelo/dossier/sanitize.py, tests/dossier/test_pdf.py, tests/dossier/test_sanitize.py
      Verify:  the tests are written first and fail; then the PDF has its index, the records in time
               order, each file's metadata and digest, and the cited sections
      Done:    stored in S3 for the tenant to download, with an audit entry
- [ ] T044 [US3] Web: build and download a dossier
      Req:     REQ-013, NFR-009
      Design:  docs/design/web.md, docs/design/web/dossier.svg
      Files:   web/src/…
      Verify:  the tests are written first and fail; then axe reports 0 violations on the screen
      Done:    matches the reference, with live data from staging

**Checkpoint:** US3 is independently demoable on staging.

---

## Phase 6 — US4 Ask a rights question

- [ ] T045 [US4] Write the curated topics, each answer citing its sections
      Req:     REQ-014, REQ-006
      Design:  docs/design/navigator.md
      Files:   docs/legal/topics/*.md, tests/unit/test_topics.py
      Verify:  the tests are written first and fail; then every topic cites at least one section,
               and only sections in T022's curated set
      Done:    the topics include repairs, entry, deposits, lock-outs and services, and eviction
- [ ] T046 [US4] Answer a question, or say it's outside the topics
      Req:     REQ-014
      Design:  docs/design/navigator.md, docs/design/api.md
      Files:   src/tokelo/api/navigator.py, tests/api/test_navigator.py
      Contract:POST /api/navigator {question} → {topic, answer, sections} or {outside: true, refer_to}
      Verify:  the tests are written first and fail; then curated questions get their topic, and
               others are told plainly and pointed to the Rental Housing Tribunal
      Done:    no answer cites case law
- [ ] T047 [US4] Web: ask a question
      Req:     REQ-014, NFR-009
      Design:  docs/design/web.md, docs/design/web/navigator.svg
      Files:   web/src/…
      Verify:  the tests are written first and fail; then axe reports 0 violations on the screen
      Done:    matches the reference, with live data from staging

**Checkpoint:** US4 is independently demoable on staging.

---

## Phase 7 — Hardening and release

- [ ] T048 [POL] Delete an account and everything in it
      Req:     REQ-016
      Design:  docs/design/api.md, docs/design/web.md, docs/design/web/account.svg
      Files:   src/tokelo/api/account.py, tests/api/test_delete_account.py, web/src/…
      Verify:  the tests are written first and fail; then the tenant's files and records are gone,
               and the audit log keeps its entries without the tenant's identity
      Done:    the web app deletes the Cognito user with the tenant's own token
- [ ] T049 [POL] Measure the API's speed in the release pipeline
      Req:     NFR-001, NFR-002
      Files:   perf/upload-url.js, perf/first-request.js
      Verify:  k6 reports an upload URL at p95 < 500 ms warm, and the first request after 15 minutes idle within 30 s
      Done:    both run in the release pipeline, with their `req:` lines
- [ ] T050 [POL] Set the service level objectives, including the dead-letter rate
      Req:     NFR-007
      Files:   docs/ops/slo.toml
      Verify:  `scripts/realm/realm release slo-check` passes; the objective for jobs reaching a
               dead-letter queue is at most 1% over 7 days
      Done:    the release's watch window reads them
- [ ] T051 [POL] Record the inspections: network isolation and the budget
      Req:     REQ-018, REQ-019, NFR-008
      Files:   docs/ops/inspections.md
      Verify:  the deployed route tables and security groups, and the budget, are checked against
               REQ-018, REQ-019 and NFR-008, with the commands and their output
      Done:    each inspection is dated, with what it found
- [ ] T052 [POL] Pass the Concept and Development gates
      Req:     none — lifecycle gates (GATES.md)
      Files:   REQUIREMENTS.md (states), GATES.md
      Verify:  `realm trace` shows every requirement in the first release approved, with its tasks
               and tests; `realm gates` passes
      Done:    both gates have dated entries with their evidence
- [ ] T053 [POL] Release v1.0.0: staging, UAT, production, promote (with Katlego's go-ahead at each step)
      Req:     none — the release (GATES.md, Release)
      Verify:  the release record shows every check passed and the UAT sign-off; production is
               applied through realm-infra; the promote workflow succeeds and the watch window holds
      Done:    the Release gate has its dated entry
- [ ] T054 [POL] Sweep for placeholders: no `TODO`/`FIXME`/stub bodies/hard-coded sample data
      remain outside of tasks that explicitly declared them, and each declared one has an open
      follow-up task ID.
      Req:     none — the kit's closing sweep
      Verify:  the gate's placeholder sweep is clean on `main`
      Done:    nothing ships unfinished

---

## Secret Realm: every task traces to a requirement

Every task also carries a **Req:** field, next to Design, Files, Contract, Verify and Done:

```
      Req:     REQ-012, NFR-003          the requirements it serves
      Req:     none — <why>              tooling, refactoring or docs: say which
```

`scripts/realm/realm trace` (part of the gate) refuses a task without one, a commit that names no
task, and an approved requirement that no task or test names.

## Standing tasks

- [ ] T000 [MNT] Keep the project maintained: dependency updates, runtime upgrades, and the weekly gate's findings
      Req:     none — preventive and adaptive maintenance (ISO/IEC 14764)
      Verify:  the weekly realm-scheduled run is green
      Done:    never: it stays open for the life of the project
