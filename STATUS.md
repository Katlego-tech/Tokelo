# `Tokelo` — STATUS

> Source of truth for "what's going on right now." Read first, update last. Treat updating it as
> part of "done."

_Last updated: 2026-09-25 — by Katlego (via Claude Code)_

---

## ⇄ HANDOFF: **none**

> Leave this block here even when dormant — it is the first thing every AI reads, and it only
> works as a signal if it always lives in the same spot. Set it to `ACTIVE` and fill the rows
> when handing work to another AI or another session. See
> [docs/cross-ai-protocol.md](docs/cross-ai-protocol.md) § Handoffs.

| Field | Value |
|---|---|
| Status | 🟢 **none** |
| Raised | — |
| Reason | — |
| Document | — |
| Branch | — |
| Resume at | — |
| Blocking | — |

---

## 🎯 Current focus — the taskboard (claim your lane here)

> **WIP limit: one lane in `🟡 Doing` per contributor, human or AI. Finish before you start.**
> Work parked in Doing while you work elsewhere makes this table a lie, and a board that lies is
> worse than no board. Park it back to `⬜ To Do` with a Log note, or write a handoff.
> Status values: `⬜ To Do` · `🟡 Doing` · `🔵 In review` · `✅ Done` · `🔴 Blocked`.
> ("Lane" here means an *area of ownership*; the Status column is the *flow state*.
> See [docs/iteration-rituals.md](docs/iteration-rituals.md).)

| Lane | Owner | AI | Status |
|------|-------|----|--------|
| `infra` (T018–T020: staging's network, tables, storage, events, identity, API, functions) | Katlego | Claude Code | ✅ Done |
| `release` (T021: v0.1.2 staged) | Katlego | Claude Code | 🔵 In review — PR #26 waits for the UAT sign-off |
| `core` + `api` (T023–T026: the store, tenant-scoped reads, pre-signed uploads, the job spine) | Katlego | Claude Code | ✅ Done |
| `web` (T027, T035: the notice, sign-up, sign-in, the uploader, a lease's flags) | Katlego | Claude Code | ✅ Done |
| `legal` (T022: the curated sections of the four sources) | Katlego | Claude Code | ✅ Done |
| `ocr` (T028–T033: the samples, the reader, the splitter, the catalogue, the intake, the flags) | Katlego | Claude Code | ✅ Done |
| `ocr` (T057: the worker — the lease job, the fan-out, the analysis) | Katlego | Claude Code | ✅ Done |
| `evidence` (T037, T038: the digest, the capture metadata, and the worker) | Katlego | Claude Code | ✅ Done |

## ⏭️ Next action

Three things for Katlego, none of them blocking Phase 2:

1. **Cut `v0.2.0`** when you want to walk the app on staging: everything since `v0.1.2` — the
   store, the uploads, the web app — is merged but undeployed.
2. **Sign off UAT on PR #26** (or say what to try first) — that's where the `v0.1.2` record waits.
   The next release will carry the web app, so a walk-through on staging can be part of it: create
   an account, confirm the emailed code, and upload a lease.
3. **Turn on** Settings → Actions → General → Workflow permissions → *"Allow GitHub Actions to
   create and approve pull requests"*, so the pipeline opens its own record PRs.
4. **Subscribe an address** to `tokelo-staging-alerts` (one `aws sns subscribe`, then confirm by
   email): the dead-letter alarms have nowhere to go until then.

Phase 3 is nearly done: the lease check works end to end in code — an uploaded lease is checked,
read, split, flagged and stored by the `ocr` worker (T057). The screen that shows it is in too
(T035). What is left in Phase 3 is T036, which times a real lease on staging and so waits for a
release.

## 🗓️ Timeline to `TBD (before 2027-02-26)`

> The AWS free plan ends 2027-02-26, or when the USD 100 of credits run out (ADR-0003).

| Phase | What | Target window | Status |
|-------|------|---------------|--------|
| Phase 0 | Design: the ADRs, the requirements, a design doc per lane (T001–T010) | to 2026-09-19 | ✅ |
| Phase 1 | Setup: the skeletons, the AWS bootstrap, the seed, staging's infrastructure (T011–T021) | 2026-09-19 → 2026-09-20 | ✅ |
| Phase 2 | Foundational: the curated sources, the store, sign-in, uploads, the event path | 2026-09-20 → 2026-09-21 | ✅ |
| Phase 3 | US1: the lease check — the samples, the reader, the clauses, the rules, the intake | 2026-09-21 → | 🟡 |
| Phases 4–7 | US2 evidence, US3 the dossier, US4 the navigator, then hardening | | ⬜ |

## 🧱 What's built so far

- **The design:** ADR-0001 to ADR-0010 (accepted, frozen; 0005 superseded by 0009), SPEC.md,
  REQUIREMENTS.md (38), PLAN.md, TASKS.md (56), the architecture and the eight design docs.
- **The code:** the four services (`api`, `ocr`, `evidence`, `dossier`) with their health
  handlers and Dockerfiles; the `api` serves the web app from its own image (ADR-0010); the web
  skeleton; the unit and API tests. The gate is green and required on `main`.
- **AWS:** the bootstrap (state bucket and key, the OIDC provider, the four CI roles and the
  permissions boundary, four ECR repositories, the USD 20 budget) — T016.
- **The seed:** `v0.0.0` built reproducibly, signed, and archived to ECR by digest — T017.
- **Staging, in full:** the VPC with no way out, its app subnets and route table, the S3 and
  DynamoDB gateway endpoints, the `fn` security group and the two tables (T018); the documents
  bucket, the four queues with their dead-letter queues, the event rules and the alarms (T019);
  the Cognito pool, the HTTP API and the four functions (T020). It answers at
  `https://525zi4zedi.execute-api.eu-west-1.amazonaws.com`: the web app at `/`, `{"ok": true}` at
  `/health`, and 401 for `/api/…` without a token.
- **A release through the pipeline** (T021): `v0.1.2` is staged — built twice to the same digest
  (except `ocr`, T056), signed, archived by digest, deployed to all four functions, and past the
  smoke, accessibility and DAST checks with no warnings.

## 🛠️ Environment & access

- **Account** 753176172735, region `eu-west-1`, **the AWS free plan** — no Organization, no
  IAM Identity Center: creating either moves the account to the paid plan and expires the credits.
- Katlego signs in with `aws login --profile tokelo` (IAM user `katlego-admin`, no access keys).
  Sessions are short: re-run it before any `aws` command here.
- CI signs in by OIDC as the four roles; the repository variables hold their ARNs and the region.
- The repository is public; `main` needs a PR and a green `gate`.

## ⚠️ Open decisions / risks

- **The free plan is the constraint.** Everything is sized to about USD 9–10 a month (ADR-0003).
  Nothing may create an Organization, a NAT gateway, an interface endpoint or a customer KMS key.
- **Textract refuses this account** (`SubscriptionRequiredException`), so OCR is open source:
  the PDF's text layer, then Tesseract, English only (ADR-0009).
- **The OCR numbers rest on synthetic samples.** 4.3% and 6.1% on the sample photographs is
  comfortably inside NFR-005's 15%, but those pages are clean Helvetica degraded on purpose. A
  creased, off-white lease under a kitchen light is harder, and T036 is where that gets found out.
- **Every uploaded kind now has a worker.** A lease reaches `ocr` (T057); a photo, a notice and
  a chat export reach `evidence` (T037), which fingerprints them. What those three still lack is
  what is *read* out of them: the timeline entries a notice or a chat export makes (T041). A
  photo's own metadata is in (T038).
- **Staging runs `v0.2.1`** (2026-09-21): the store, the uploads, the web app and the whole lease
  check, with every release check green. Its record is PR #47, waiting for a UAT sign-off.
  `v0.2.0` staged first and was rejected by DAST over ZAP rule 10096, which read SHA-256 round
  constants in the bundle as Unix timestamps; that is decided in `docs/release/zap-rules.tsv`.
- **The `ocr` image carries 284 known vulnerabilities** against 5 for the other three (the
  v0.2.1 record). That is the Debian base Tesseract forces (ADR-0009); nobody has assessed them
  yet, and production should not happen before somebody has.
- **Lambda's account concurrency is 10.** The design needs 9 (the `api`, plus 2 per trigger), so
  no function may reserve concurrency (docs/design/infrastructure.md §10).
- **Aurora is not available to this account.** A free-plan account can only create an Aurora
  cluster outside a VPC, on the internet, so the store is DynamoDB (ADR-0011, 2026-09-20). Any
  future "just add a database" instinct should read that ADR first.

## 🔄 Retrospectives (one per phase boundary)

> Prime directive: *every person did the best they could, given what was known at the time.* The
> useful question is what the **written process** failed to say — a design doc that skipped a
> diagram, a `Done:` that wasn't observable, a contract two lanes read differently. Blaming an AI
> is especially useless: it will agree and then repeat the mistake next session. Only a change to a
> file changes the outcome. Format: [docs/iteration-rituals.md](docs/iteration-rituals.md).

### `Phase 0 → Phase 1` — 2026-09-19

- **What happened:** the design landed as planned; setup then hit three defects in the kit
  itself (Semgrep on the kit's own Terraform, `realm-infra` applying before the bootstrap, and
  GitHub's immutable OIDC subjects), and a fourth at the seed (`publish` asking for URLs that
  only T020 creates).
- **Why:** the kit had never been run end to end on a new AWS account, so its first-run path was
  the least-tested one — and nothing in it said which checks belong to which command.
- **Committed change:** each was fixed in SecretRealm with a test that fails without the fix
  (PRs #14–#17) and synced here, rather than worked around in this project.

## 🗒️ Log

> This is the standup. Every session ends with a line here: **done / next / blocked.** Two or three
> lines — if it needs more, it's a handoff document. Name blockers, don't solve them here.

- 2026-09-25 — Katlego (via Claude Code) — T058: README.md added (the repo had none): the overview,
  where to start, the quick start, and the WeThinkCode_ submission code `WTC-5JF7FDRM`. Next:
  merge the PR so the daily check finds the code on `main`. Blocked: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T038: what a photograph says about itself. Capture
  time with its offset, the phone, and the coordinates with the right sign for the southern
  and eastern hemispheres — read from the first chunk the digest already streamed, so a 20 MB
  photo is never held whole. Nothing is inferred: a photo with no time gets no timeline entry
  rather than one dated to the upload. Found and fixed a real bug on the way — `Capture.item()`
  handed DynamoDB raw floats, which boto3 refuses. Next: T039, verifying a file. Blocked on:
  nothing.
- 2026-09-21 — Katlego (via Claude Code) — T037: the evidence worker. Every photo, notice and
  chat export fingerprinted from the stored object by version, streamed so a 20 MB photo is
  never held whole, dated by the object's own LastModified, and audited once under the
  tenant's pseudonym. The lanes now share one fake S3 (tests/fakes.py) instead of a copy
  each. Next: T038, the capture metadata. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — `v0.2.0` staged and rejected by DAST on one new
  ZAP warning: Timestamp Disclosure [10096], five ten-digit numbers in the app's bundle. They
  are SHA-256 round constants from @aws-crypto/sha256-js, which aws-amplify uses for Cognito
  sign-in — hex in the source, decimal after esbuild. Decided in zap-rules.tsv with that
  reason and the scan re-run clean. `v0.2.1` carries it. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T035: `/lease/:id`, the screen a tenant came for.
  Every clause with its number, its page, the lease's own words, and either a flag with the
  section it rests on or the API's own "no issue found by these checks". It waits on the 409
  while the workers read rather than showing half a lease, and names the pages that defeated
  the reader above every flag. axe clean in both states. api.md §6 gained `page_count` first,
  in its own PR, because the wireframe states it and the view didn't send it. Phase 3 is done
  but for T036, which needs staging. Next: `v0.2.0`, or Phase 4 from T037. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T034: `GET /api/leases/{id}/flags`. The whole lease,
  clause by clause, each flag with its explanation and the curated section it rests on, the
  unreadable pages by number, and the legal-information notice on every answer. Another
  tenant's lease is a 404, not a 403; a lease still being read is a 409, not half of itself.
  Next: T035, the screen that shows them. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T057: the `ocr` worker wired end to end. A lease
  upload is checked, fingerprinted, and read — a digital one finished in that same invocation
  from its text layer, a scan fanned out one job per page — and whichever invocation makes
  pages_done equal page_count runs the analysis, settled by an atomic counter rather than a lock.
  A refused file fails with its reason; a redelivered job changes nothing. US1 is code-complete
  but for the API and the screen. Next: T034 (serve a lease's flags), then T035. Blocked on:
  nothing — `v0.2.0` is what would put any of Phase 2 or 3 on staging.
- 2026-09-21 — Katlego (via Claude Code) — T033: the flags. Every rule run against every clause
  of a lease, each flag carrying the sentence a tenant reads, the sections it rests on and the
  catalogue's version; a clause nothing matched says "no issue found by these checks" and never
  that it is lawful (REQ-007). All ten terms planted in the sample lease are found. Wrote T057:
  T028–T033 built the whole `ocr` lane and no task wired it to a job. Next: T057, then T034.
  Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T030: what this project will take. One table of
  kinds, types and sizes, read both when the URL is signed and when the worker opens the file —
  and the worker reads the type out of the bytes, so a .docx renamed .pdf, a 31-page PDF and an
  image claiming 900 million pixels are all refused with a reason a tenant can read. Next: T033,
  the flags. Blocked on: nothing.
- 2026-09-19 — Katlego (via Claude Code) — T011–T016: the manifest and tests, the four services,
  the web skeleton, branch protection, the AWS bootstrap. Next: the seed. Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T017: `v0.0.0` archived to ECR after SecretRealm
  PR #17 freed `publish` from the URL check. Next: T018. Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T018: the network applied, then Aurora was refused by
  the free plan; ADR-0011 moved the store to DynamoDB and the tables are live. T019: the bucket,
  the queues, the rules and the alarms. Next: T020. Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T020: staging is complete and answering; realm.toml has
  its URL. Three kit defects on the way (SecretRealm PRs #18–#20: /tmp sizing, a policy made in
  the same apply, and the URLs each release command asks for). Next: T021, the first staging
  release. Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T023, T024 and T025: the store (two tables, the keys,
  the conditional writes), the first /api/ reads scoped to the tenant in the token, and pre-signed
  POST uploads that never let a file's bytes through the API. 26 tests against DynamoDB Local.
  Next: T026. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T029: the reader. Text layer first, then Tesseract
  5.5.0 in the ocr image, with the preprocessing a phone photograph needs. Measured: 0.1–0.2% on
  the scan, 4.3% and 6.1% on the photographs, all inside NFR-005, and under 3 s a page against
  NFR-004's 30 — so ADR-0009 stands. Next: T030, then T033. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T028 and T031: one sample lease in three forms
  (digital, scanned, photographed), the accuracy test that will grade the reader against NFR-004
  and NFR-005, and the clause splitter. End to end on the sample: 20 clauses, the ten planted
  ones flagged, the fair ones untouched. Next: T029, the reader itself. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T032: the rule catalogue — 10 rules over the curated
  law, each with the sentence a tenant reads, checked against its own example and counter-example
  when it loads. Next: T028's sample leases, then T029's OCR. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T022: the curated law — 15 sections across the Rental
  Housing Act, the Consumer Protection Act, the PIE Act and Gauteng's Unfair Practices
  Regulations, each with its source, date and amendment history. Phase 2 is done. Next: Phase 3,
  from T028. Blocked on: nothing.
- 2026-09-21 — Katlego (via Claude Code) — T027: the web app's first screens — the privacy notice
  before the account, sign-up with its emailed code, sign-in, and the uploader that posts a file
  straight to storage. 21 screen tests, axe clean on all four screens. Next: T022 (the statutes'
  real text) closes Phase 2. Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T026: the job spine — every worker's reading of an SQS
  batch, its per-message failure reporting, and the third failure that marks the document failed
  and still redrives. Next: T027 (the web sign-up and upload), or T022 with real statute text.
  Blocked on: nothing.
- 2026-09-20 — Katlego (via Claude Code) — T021: the Concept and Development gates recorded
  (scoped to the setup release), the SLOs written, and `v0.1.2` staged with every check green.
  v0.1.0 and v0.1.1 were rejected by DAST on the way and their fixes are in. Next: Phase 2, from
  T022. Blocked on: nothing — three things wait for Katlego under Next action.
