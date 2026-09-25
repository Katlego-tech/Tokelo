# Tokelo

Tokelo is a cloud-native platform on AWS for South African residential tenants. It reads uploaded
leases with open-source OCR, checks their clauses against the Rental Housing Act, the Consumer
Protection Act and the PIE Act, and explains each clause in plain language. It keeps
tamper-evident inspection evidence (SHA-256 checksums and EXIF metadata), and it compiles indexed
dispute dossiers for the Rental Housing Tribunal and the Small Claims Court.

Tokelo gives legal information, not legal advice.

## Where to start

| Read | For |
|---|---|
| [STATUS.md](STATUS.md) | What's happening right now, and who owns which lane |
| [SPEC.md](SPEC.md) | What Tokelo does |
| [PLAN.md](PLAN.md) | How it gets built, and the non-negotiables |
| [TASKS.md](TASKS.md) | The task list |
| [AGENTS.md](AGENTS.md) | The rules every contributor, human or AI, works by |
| [docs/](docs/) | Architecture, design docs, testing, git workflow |

## Quick start

```bash
bash install-hooks.sh        # once per clone: blocks pushes to main, runs the gate before a push
bash scripts/gate.sh         # the gate: lint, tests, build, placeholder and secret sweeps
```

All work reaches `main` through a pull request. See [docs/git-workflow.md](docs/git-workflow.md).

## Submission reference

WeThinkCode_ Cohort 2025 elective, proof-of-work verification code: `WTC-5JF7FDRM`
