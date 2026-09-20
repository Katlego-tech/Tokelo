# `Tokelo` — STATUS

> Source of truth for "what's going on right now." Read first, update last. Treat updating it as
> part of "done."

_Last updated: 2026-09-20 — by Katlego (via Claude Code)_

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

## ⏭️ Next action

Three things for Katlego, none of them blocking Phase 2:

1. **Sign off UAT on PR #26** (or say what to try first) — that's where the `v0.1.2` record waits.
2. **Turn on** Settings → Actions → General → Workflow permissions → *"Allow GitHub Actions to
   create and approve pull requests"*, so the pipeline opens its own record PRs.
3. **Subscribe an address** to `tokelo-staging-alerts` (one `aws sns subscribe`, then confirm by
   email): the dead-letter alarms have nowhere to go until then.

Then Phase 2 begins at T022 (the curated legal sections) and T023 (the store).

## 🗓️ Timeline to `TBD (before 2027-02-26)`

> The AWS free plan ends 2027-02-26, or when the USD 100 of credits run out (ADR-0003).

| Phase | What | Target window | Status |
|-------|------|---------------|--------|
| Phase 0 | Design: the ADRs, the requirements, a design doc per lane (T001–T010) | to 2026-09-19 | ✅ |
| Phase 1 | Setup: the skeletons, the AWS bootstrap, the seed, staging's infrastructure (T011–T021) | 2026-09-19 → 2026-09-20 | ✅ |
| Phase 2 | Foundational: the curated sources, the store, sign-in, uploads, the event path | next | ⬜ |
| Phases 3–7 | US1 the lease check, US2 evidence, US3 the dossier, US4 the navigator, then hardening | | ⬜ |

## 🧱 What's built so far

- **The design:** ADR-0001 to ADR-0010 (accepted, frozen; 0005 superseded by 0009), SPEC.md,
  REQUIREMENTS.md (38), PLAN.md, TASKS.md (55), the architecture and the eight design docs.
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
- 2026-09-20 — Katlego (via Claude Code) — T021: the Concept and Development gates recorded
  (scoped to the setup release), the SLOs written, and `v0.1.2` staged with every check green.
  v0.1.0 and v0.1.1 were rejected by DAST on the way and their fixes are in. Next: Phase 2, from
  T022. Blocked on: nothing — three things wait for Katlego under Next action.
