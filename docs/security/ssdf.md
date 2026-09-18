# The Secure Software Development Framework, mapped to this kit

NIST SP 800-218 (SSDF v1.1) groups secure-development practices into four families. This table
says, for every practice, which part of a Secret Realm project covers it and what enforces it. It's
the answer to "how do you know you do that?"; a practice marked **process** is a habit the kit
documents but can't check.

**Enforced by:**
- **gate:** `scripts/gate.sh`, on every push and PR
- **release:** the release workflow
- **scheduled:** the weekly workflow
- **setup:** when the project is created
- **process:** a documented habit

## PO: Prepare the organisation

| Practice | What it asks | Where it's covered | Enforced by |
|---|---|---|---|
| PO.1 Define security requirements | infrastructure, software and third-party security requirements, kept current | security needs are requirements like any other: `NFR-` entries with the ISO/IEC 25010 characteristic `security` (REQUIREMENTS.md) | gate (`req-lint`, `trace`) |
| PO.2 Roles and responsibilities | who does what, and training | AGENTS.md roles and lanes; STATUS.md ownership; solo mode's AI reviewer | process |
| PO.3 Supporting toolchains | the tools, their configuration, and their outputs kept as evidence | one gate for the hook and CI; pinned tool versions (osv-scanner, jscpd, Semgrep; Terraform, tflint and checkov where there's `infra/`); release records keep each check's result | gate, release |
| PO.4 Criteria for security checks | defined criteria, and the information to judge them | the gate's checks and the release checks, each with a pass rule; the skip rule (a check that can't run fails) | gate, release |
| PO.5 Secure development environments | separated, hardened environments and endpoints | secrets only in `.env` (never committed); dev, staging and production kept apart on the platform; branch protection | gate (secret sweep), setup |

## PS: Protect the software

| Practice | What it asks | Where it's covered | Enforced by |
|---|---|---|---|
| PS.1 Protect all forms of code | against unauthorised access and tampering | a private repo or branch protection; commits reach `main` through reviewed PRs; the pre-push hook | setup (the `assured` tier refuses without protection), gate |
| PS.2 Verify release integrity | a way for users to verify what they got | each release image signed with cosign, with a provenance file; the reproducible-build check | release |
| PS.3 Archive and protect each release | keep the files and their provenance | the release record (`docs/releases/vX.Y.Z.md`), the SBOM, the digests, and the image kept in the registry | release |

## PW: Produce well-secured software

| Practice | What it asks | Where it's covered | Enforced by |
|---|---|---|---|
| PW.1 Design to meet security requirements | threat modelling and risk-based design | a STRIDE threats section in every design doc; C4 diagrams showing the trust boundaries | gate (`design-check`) |
| PW.2 Review the design | against the requirements and the risks | design docs and ADRs merged through PRs, reviewed before the build tasks start | process, gate (`adr-check`) |
| PW.4 Reuse well-secured software | vetted components instead of new code for solved problems | declared, pinned dependencies with committed lockfiles, scanned for known vulnerabilities | gate (osv-scanner) |
| PW.5 Secure coding practices | code written to secure-coding standards | lint and type checks; no placeholders; secrets never in code | gate (lint, pyright, placeholder and secret sweeps) |
| PW.6 Secure build configuration | compiler, interpreter and build settings that improve security | builds only in CI from the lockfiles; container images run without root | release |
| PW.7 Review and analyse the code | human review and static analysis | PR review (a teammate, or a fresh AI session in solo mode); Semgrep | gate (Semgrep), process |
| PW.8 Test the executable | find vulnerabilities in the running software | a DAST baseline scan (OWASP ZAP) against staging on every release; performance and accessibility checks | release |
| PW.9 Secure defaults | secure settings out of the box | DEBUG off, secrets required, and a user without root rights in the production images; feature flags off by default; checkov on the Terraform in `infra/`, each skip with its reason | gate, release, process |

## RV: Respond to vulnerabilities

| Practice | What it asks | Where it's covered | Enforced by |
|---|---|---|---|
| RV.1 Identify vulnerabilities continuously | watch for new vulnerabilities in what's shipped | the gate re-run weekly on the default branch, so new advisories surface on quiet repos; a dependency-update bot | scheduled |
| RV.2 Assess, prioritise and remediate | fix according to risk | osv-scanner exemptions must carry a reason; an incident record for anything that reached production | gate, process |
| RV.3 Find root causes | learn from each vulnerability | blameless postmortems that end in a committed change to a file, not a resolution to "be careful" | process |

PW.3 isn't missing: SSDF v1.1 folded it into PW.4.

The rows marked release or scheduled are built in phases 3 and 5 of DESIGN.md §12. Until then,
they say what the release pipeline and the weekly workflow will enforce.
