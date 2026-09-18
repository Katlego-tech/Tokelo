# Testing strategy ("main is always green")

The whole workflow exists to guarantee one thing: **only ever push working, tested code to `main`.**
This is how parallel contributors (human or AI) avoid breaking each other's work and always have a
demo-ready product.

## The rule

> **No stage advances without passing tests. Every feature ships with its tests.**

A task in [TASKS.md](../TASKS.md) is not `[x]` done until its tests exist and pass.

## The two gates

Both run the same script, [`scripts/gate.sh`](../scripts/gate.sh) — there is one gate with two
triggers, not two gates that can disagree.

1. **Local pre-push hook** (`.githooks/pre-push`) — runs it before every `git push`, and blocks the
   push if anything fails. Enable once per clone: `bash install-hooks.sh`.
2. **CI** (`.github/workflows/ci.yml`) — runs it again on every push and PR to `main`. The authority,
   since the hook is opt-in and bypassable, plus the place for anything too slow or expensive to run
   on every local push (real-model integration tests, latency benchmarks).

**A check that did not run is a failed check.** If a layer's tooling isn't installed, the gate fails
and names what's missing — it does not skip and report green. That distinction is not pedantry: the
earlier version of this kit skipped anything it couldn't run and printed "Test gate passed", which
meant an untested push and a passed push looked identical. Full rationale, and the table of what now
fails instead of skipping, in [git-workflow.md](git-workflow.md#the-skip-rule).

What legitimately reports "nothing to do" is a repo with **no code in it yet** — and it says exactly
that, rather than claiming a pass.

## Different kinds of tests

Unit tests are not the only kind, and the distinction that matters is **who the test speaks for**:

| | Unit | Integration | Acceptance |
|---|---|---|---|
| Speaks for | the developer | the system's own wiring | **the user / the spec** |
| Asks | "does this function do what I meant?" | "do these parts actually talk?" | "does the product do what was asked?" |
| Written from | the implementation | the component boundary | the **story**, before the code |
| Fails when | logic is wrong | a seam is wrong | the feature is wrong |

A suite of only unit tests can be entirely green while the product does the wrong thing correctly.
Acceptance tests are what stop a lane coming back adjacent-but-wrong — the same failure mode the
design docs exist to prevent, caught mechanically instead of at review.

### Acceptance tests start with a story

The Curriculum's Acceptance Tests topic is blunt about the order: it starts with a story, then the
story is represented in code. A story with no scenarios is not ready to build, and a scenario is
exactly the thing an acceptance test asserts.

```
Story:    As a <role>, I want <capability>, so that <why it matters>.
Scenario: Given <starting state>
          When  <the action>
          Then  <the observable outcome>
```

Write the scenarios in [SPEC.md](../SPEC.md) with the story, and name the scenario in the task's
`Verify:` line so the task and the test refer to the same sentence:

```python
# Story: launch a robot into the world
# Scenario: the world is full
def test_launch_into_full_world_is_refused(world_with_no_free_space, client):
    response = client.launch("HAL")
    assert response.result == "ERROR"
    assert "no more space" in response.message.lower()
```

The test reads like the scenario on purpose. When it fails, the failure names a user-visible
behaviour, not an implementation detail — which is what makes it survive a refactor.

## Test layers

> 📝 **Customize:** keep the rows that apply, delete the rest, add project-specific ones (schema
> validation, compliance math, latency budgets — whatever your PLAN.md non-negotiables demand).

| Layer | Tool | What it proves |
|-------|------|----------------|
| **Unit** | `<pytest / vitest / jest / ...>` | A function/service works in isolation; **external AI/API calls are mocked** (fast, no key, no cost). |
| **Acceptance** | `<pytest / vitest against the real interface>` | A **scenario from SPEC.md** holds, asserted through the same interface a user or client uses — not through internals. |
| **Schema/contract** | `<jsonschema / pydantic / zod>` | Structured outputs validate against your I/O contract. |
| **Grounding** (if the project generates AI content) | — | Every generated fact/entity actually traces back to the source input — the anti-hallucination test. |
| **Integration** | `<httpx / supertest>` | Endpoints wire through service → repo → DB correctly (test DB). |
| **End-to-end** | — | The full golden path, on a fixed sample input. |
| **Frontend** | `<Testing Library / Playwright>` | Components render; the critical user flow works. |

## Integration tests against real infrastructure

Unit tests mock the broker and datastore; integration tests should exercise the real ones. Stand
them up with the project's `docker-compose.yml` (the same one used for local dev — see
[architecture-defaults.md](architecture-defaults.md) §4) rather than mocking Kafka/RabbitMQ or the
DB, so the test proves the actual wire format and delivery semantics. Keep these in the CI lane, not
the pre-push hook, if they're slow to spin up — `docker compose up -d` in CI, tear down after. Pin
the broker/datastore image versions (architecture-defaults §5) so a test failure is never "the image
silently moved."

## Mocking AI/external calls in tests

Unit tests must not call real external models or paid APIs (slow, costs money, needs a key,
non-deterministic). Wrap every such call behind a service interface and inject a fake in tests that
returns canned, deterministic output. Keep a **small, opt-in live smoke test** (skipped unless the
relevant API key is set) to catch real integration drift — run it manually before a checkpoint/release,
not in every CI run.

## Grounding tests (if your project generates content from a source)

If any part of the system produces "facts" derived from user-supplied input (a document, a
transcript, a database), assert grounding explicitly rather than trusting the model's output on
faith:

```python
def test_extracted_entities_are_in_source(sample_input, extraction_service_fake):
    result = extraction_service_fake.extract(sample_input.text)
    for entity in result.entities:
        assert entity.name.lower() in sample_input.text.lower()
```

This is the single test category most worth having in any AI-generating pipeline — hallucinated
output in a real deliverable (a schedule, a report, a citation) is the failure mode that actually
hurts users, not a missed edge case.

## Golden-path regression tests

Lock a small, fixed set of representative inputs (e.g. 2-3 known examples covering distinct
categories) and assert structure + key properties of the output stay stable across changes. Cheap to
maintain, catches regressions that unit tests miss because they mock too much.

## Coverage expectations

- Business logic and anything that could silently produce wrong output: high coverage — this is the
  risk surface.
- Endpoints: at least a happy-path + an auth-failure + a validation-failure test each.
- Don't chase 100% on glue code; do cover anything that could ship a wrong answer quietly.

## Definition of Done (testing slice)

- [ ] New/changed behavior has tests; `bash scripts/gate.sh` is green locally — and green because it
      **ran** the suite, not because it found nothing to run (check the count it prints).
- [ ] If the task implements a scenario from SPEC.md, an acceptance test asserts that scenario.
- [ ] CI green on the branch.
- [ ] Grounding preserved, if applicable (no path that lets the system invent unverified data untested).
