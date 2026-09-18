# Project structure

> 📝 **Customize:** replace everything below with the *actual, current* layout of this repo. This
> file exists so a new session (human or AI) can find its way around without re-deriving the tree
> from scratch, and so [AGENTS.md](../AGENTS.md) §7 can stay a short summary that links here for
> detail. Keep it in sync when the shape of the repo changes — a stale structure doc is worse than
> none, because it actively misleads.

## The tree

The default shape (see [docs/architecture-defaults.md](architecture-defaults.md)) is microservices +
a broker + a shadcn/ui frontend. Replace the `services/*` and `apps/*` contents below with what this
project actually has — the point is the top-level shape, not these exact names.

```
<project-name>/
├── README.md              <- human overview + quick start
├── AGENTS.md               <- the rules (every session reads this)
├── STATUS.md                <- LIVE board: done / in-progress / next  (read first, update last)
├── <CLAUDE.md / GEMINI.md / ...>  <- per-tool entry points
├── SPEC.md · PLAN.md · TASKS.md   <- the planning documents
├── DESIGN-DOC.template.md   <- copied per lane to docs/design/<lane>.md, before that lane is built
├── docs/                    <- this documentation (architecture, pipeline, testing, structure...)
│   ├── architecture-defaults.md  <- the microservices/messaging/shadcn defaults + any deviations
│   ├── design-documentation.md   <- draw it before you build it: which diagram, when, why
│   └── design/                   <- the per-lane design docs implementation is checked against
├── .claude/                  <- agents (code-explorer/architect/reviewer), the feature-dev command,
│                                 the frontend-design skill
├── scripts/gate.sh           <- THE gate: lint, tests, build, placeholder + secret sweeps
├── .githooks/pre-push        <- branch protection, then runs scripts/gate.sh
├── .github/workflows/ci.yml  <- runs the same scripts/gate.sh -- never a second set of checks
├── install-hooks.sh          <- run once per clone, by every contributor
├── services/                  <- one directory per microservice (one bounded context each)
│   ├── <service-a>/            <-   its own Dockerfile, tests, and datastore where reasonable
│   └── <service-b>/
├── broker/ or infra/           <- Kafka/RabbitMQ config, topic/queue docs
├── docker-compose.yml          <- spins up every service + the broker + any datastore for local dev
└── apps/web/                   <- the shadcn/ui frontend (Radix + Tailwind + CVA), thin over the services
```

## Why this shape

`<A few sentences on the real architectural decisions: why a monorepo vs. multiple repos, why this
service boundary, what's shared between which apps, and so on. This is the part that's genuinely
project-specific — don't try to templatize it, just make sure it's written down somewhere.>`

## Run it

```bash
# fill in the real commands to boot every piece of the system locally
```

## Status

`<What's scaffold-only vs. what's real, if that distinction matters at this point in the project —
useful early on, delete once everything is real.>`
