# Architecture defaults

Every project this kit bootstraps starts from the same defaults, unless a project has a real reason
to deviate. These aren't non-negotiables in the [PLAN.md](../PLAN.md) sense (they're personal
convention, not project law) — but they're the answer when nothing in the spec forces a different
choice, so the tooling (`code-architect`, `feature-dev`) checks here before inventing something else.

## 1. Microservices by default

One service per bounded context, each with its own datastore where that's reasonable, rather than a
single monolith with internal modules. A new capability that doesn't obviously belong inside an
existing service's boundary gets its own service, not a new module bolted onto the nearest one.

**Deviate when:** the project is small enough (a weekend build, a hackathon, a single-purpose tool)
that service boundaries would be pure overhead before there's a second team or a second scaling
need. If you deviate, say so in PLAN.md's Technical Context and note it as a conscious choice, not an
oversight — the FrameFlow/OmniCaption projects this kit was distilled from were both time-boxed
enough that a single deployable made sense; that's a legitimate reason, "it's easier right now" alone
often isn't once more than one service is actually in play.

## 2. Async messaging via a broker

Services talk to each other asynchronously through a message broker rather than direct
service-to-service HTTP calls wherever the interaction can tolerate it (anything that isn't a
synchronous read the caller is blocking on). Pick **Kafka** or **RabbitMQ** per project and record
the choice + why in PLAN.md's Technical Context table:

- **Kafka** — high-throughput event streams, multiple independent consumers replaying the same log,
  event sourcing / audit trail requirements.
- **RabbitMQ** — task/work-queue routing, simpler pub-sub needs, lower operational overhead when the
  project doesn't need log retention or replay.

Synchronous HTTP/gRPC between services is still fine for request/response calls where the caller
genuinely needs an immediate answer — the default is "prefer async," not "never call synchronously."

## 3. `shadcn/ui` on the frontend

New frontend work builds on `shadcn/ui` (Radix primitives + Tailwind + CVA) as the component layer,
not a heavier all-in-one UI framework — it's copy-paste-owned code in your own tree, so it doesn't
lock you into someone else's design system. See
[.claude/skills/frontend-design/SKILL.md](../.claude/skills/frontend-design/SKILL.md): the stock
theme is exactly the "looks AI-generated" default that skill exists to avoid, so treat installed
components as unstyled structure and put a real token system (palette, type, radius, motion) on top.

## 4. Docker for every service

Every service (and the frontend, if it needs its own runtime rather than static hosting) ships with
its own `Dockerfile`, and local dev spins the whole system up with one `docker-compose.yml` at the
repo root — the services, the broker (Kafka/RabbitMQ), and any datastore. This is what makes
"microservices + a broker" actually runnable on a laptop instead of only in a deployed environment,
and it's the same mechanism [docs/testing-strategy.md](testing-strategy.md) leans on for integration
tests that need a real broker/datastore rather than a mock.

**Deviate when:** a service is trivial enough to run bare (a static frontend deployed to a CDN, a
single script with no dependencies) — containerizing it would be ceremony with no payoff. Note the
exception in `docs/project-structure.md` rather than silently leaving it out of `docker-compose.yml`.

## 5. Latest long-term-stable release, then pin it

For every language, runtime, framework, broker, and base image, choose the **latest long-term-stable
(LTS) / stable release** available at the time the project starts — not the version you happen to
remember, and not a bleeding-edge preview. Then **pin the exact version** so the choice is
reproducible:

- **Verify, don't assume.** An AI copilot's training cutoff lags reality — check the current LTS
  (the project's release page / `endoflife.date` / the registry) before writing a version number,
  rather than pinning whatever was current at training time. If you can't verify, say so instead of
  guessing.
- **Pin exactly, everywhere.** Lockfiles committed (`package-lock.json`, `poetry.lock`, `uv.lock`,
  `go.sum`, …); Docker base images tagged to a concrete version (`FROM node:22-bookworm-slim`, never
  `FROM node:latest`); broker/datastore images tagged, not `:latest`. The gate enforces the lockfile
  half: a project without a committed lockfile fails, because its dependencies can't be scanned for
  known vulnerabilities ([security-basics.md](security-basics.md#dependencies-with-known-vulnerabilities)).
- **LTS over newest-of-all** where a project publishes an LTS track (Node, Python, Java, Postgres,
  Ubuntu base images…): take the newest release *on the LTS line*, not a shorter-support current
  release, unless the project specifically needs something only the newer line has.

**Deviate when:** a dependency's LTS is genuinely too old to carry a feature you need, or the project
is a throwaway experiment where reproducibility doesn't matter. Record the versions actually chosen
in PLAN.md's Technical Context (the `Language(s)` / `Runtime` rows), and note any deliberately
non-LTS pick there.

## 6. Layers inside each service

Defaults 1–5 draw boundaries *between* services and say nothing about the inside of one — which is
where most services actually rot. The default inside a service is the **layered architecture**
(Curriculum 202, *Separation of Concerns*): each layer depends only on the one below it, and the
dependency arrow never points back up.

```
   Web API layer      HTTP, routes, serialization, status codes     ← knows about the domain
   Domain layer       entities, rules, the actual behaviour         ← knows about nothing
   Data access layer  queries, persistence, external services       ← knows about the domain
```

The test of whether you've done it: **the domain layer imports nothing from the other two.** If your
entity class imports the ORM, or the HTTP framework, the layering is decorative.

That constraint is what buys you the two things worth having:

- **The domain is testable without infrastructure.** No database, no HTTP client, no broker — which
  is what makes the unit layer in [testing-strategy.md](testing-strategy.md) fast enough to run on
  every push.
- **You can replace a layer.** Swap Flask for FastAPI, or Postgres for a document store, and the
  domain doesn't know it happened.

### Don't let the data model eat the domain

The failure mode the Curriculum names is the **anemic object model**: classes that are nothing but
fields with getters and setters, while all the actual behaviour lives in "service" or "manager"
classes operating on them from outside. It looks organized and it is a procedural program wearing
objects.

The tell is a rule that lives outside the thing it constrains: `RobotService.move(robot, direction)`
checking whether the robot is allowed to move, instead of `robot.move(direction)` enforcing it. Once
the rule is outside, it can be bypassed by any caller that forgets it — so every caller has to
remember, and eventually one won't.

Structure and behaviour belong together. This is also why the class diagram in a design doc is worth
drawing: a class diagram of an anemic model is visibly all boxes and no operations, and you can see
the problem before it's code.

### API contracts

If a service exposes an HTTP API, the contract is **OpenAPI**, committed to the repo, and it is
written before the client is built. It is the same principle as a design doc: the verbatim contract
between two lanes goes in a file both lanes read, not in a conversation. Generate it from the code or
hand-write it, but keep it in version control — a contract that only exists at runtime is a contract
nobody can review in a PR.

**Deviate when:** the service is internal, single-consumer, and both sides land in the same PR — then
the design doc's contracts section is enough on its own.

## Where this shows up

- [PLAN.template.md](../PLAN.template.md)'s Technical Context table has `Architecture`, `Messaging`,
  `Frontend`, and `Containerization` rows pre-filled with these defaults — overwrite them per project
  instead of leaving them blank.
- [docs/project-structure.md](project-structure.md)'s example tree assumes a `services/<name>/` shape,
  a broker, and a `docker-compose.yml` at the root.
- [docs/testing-strategy.md](testing-strategy.md)'s integration layer uses `docker-compose` to stand
  up the real broker + datastore instead of mocking them.
- PLAN.md's `Language(s)` / `Runtime` rows record the exact LTS versions chosen (default 5).
- `.claude/agents/code-architect.md` checks this file before defaulting a greenfield design choice.
- `.claude/commands/feature-dev.md`'s architecture-design phase points every candidate approach at it.
