# Iteration rituals

The Curriculum's Iterative Development topic describes five practices that keep a team's work
visible: a **backlog**, a **taskboard**, **standups**, **showcases**, and **retrospectives**. They
were written for a team of humans in a room. This project isn't one — it's one or two people plus
several AI copilots, working asynchronously, where a "teammate" may have no memory of yesterday.

That makes the rituals *more* necessary and changes their form entirely. Each one below is written
as it actually works here: a file, not a meeting.

> **Features are not practices.** — Curriculum 200, *Gitlab*
>
> Having a taskboard is not the same as managing flow. Having STATUS.md is not the same as keeping it
> true. The artifact is not the practice; the discipline is.

---

## Delivery model: continuous flow

The Curriculum contrasts three models — waterfall, time-boxed (fixed-length sprints), and continuous
flow (work pulled as capacity frees up). This kit is **continuous flow**: a lane is claimed, a task is
pulled, it ships, the next one is pulled. There are no sprints, because sprint boundaries assume a
team that starts and stops together, and an AI copilot's session boundary has nothing to do with a
calendar.

What continuous flow needs instead of sprint ceremonies is a **work-in-progress limit** and a board
that is actually true. Both live in STATUS.md.

---

## The backlog — [SPEC.md](../SPEC.md) and [TASKS.md](../TASKS.md)

The backlog is what to build and in what order. It splits across two files here:

- **SPEC.md holds stories.** What a user wants, and why. Written from the outside.
- **TASKS.md holds tasks.** What gets built to make a story true. Written as a contract:
  `Design: / Files: / Contract: / Verify: / Done:`.

### Titles are important

The Curriculum makes this its own heading, and it earns it. A card titled *"Fix the world"* tells you
nothing three weeks later; *"Refuse to launch a robot into a full world"* tells you what done means.
A title that doesn't contain a verb and an object is not a story yet.

### Stories and scenarios

A story that can't be broken into scenarios isn't understood well enough to build:

```
Story: Launch a robot
  As a player, I want to launch a robot into the world, so that I can start playing.

  Scenario: the world has space
    Given a world with at least one free square
    When  a player launches a robot named "HAL"
    Then  the robot appears at a free position, facing north

  Scenario: the world is full
    Given a world with no free squares
    When  a player launches a robot
    Then  the launch is refused with "no more space in this world"
```

Scenarios are the bridge between the backlog and the test suite: each one becomes an acceptance test
([testing-strategy.md](testing-strategy.md#acceptance-tests-start-with-a-story)), and a task's
`Verify:` line names the scenario it satisfies. That chain — story → scenario → task → test — is what
makes "done" checkable by someone who wasn't there.

### Who owns the backlog

Everyone contributes; one person decides order. On a project with AI copilots this needs saying
explicitly, because an AI will otherwise cheerfully invent work that nobody asked for. **AI copilots
propose backlog items; they don't add them silently.** A new task lands in TASKS.md the same way any
change lands: in a PR, with a reason.

---

## The taskboard — the Current focus table in [STATUS.md](../STATUS.md)

> A taskboard is a visualization tool that enables you to manage and optimise the flow of your work.
> The lanes on a board represent the steps in your process. — Curriculum 200, *Taskboards*

Note the collision in vocabulary, because it causes real confusion: the Curriculum's **lane** is a
*step in the process* (To Do → Doing → Done). This kit's **lane** is an *area of ownership*
(`feat/parser`, `feat/frontend-web`). Both meanings are in play, on the same table:

| Lane (ownership) | Owner | AI | Status (flow) |
|---|---|---|---|
| `parser` | Kirito | Claude | 🟡 Doing |
| `ingest` | — | — | ⬜ To Do |

The Status column is the taskboard. Keep the vocabulary straight when writing tasks: *"claim a lane"*
means take ownership of an area; *"move it to Doing"* means change its flow state.

### The WIP limit

The single most valuable thing a board does is make it visible that too much is in flight. Work
sitting in "Doing" is work that has cost time and delivered nothing yet.

> **One lane in `Doing` per contributor — human or AI. Finish before you start.**

If you need to start something else, the current lane goes back to `To Do` with a note in the Log
saying where it stands — or it gets a handoff document
([cross-ai-protocol.md](cross-ai-protocol.md)). What it does not do is sit in `Doing` while you work
on something else, because then the board is lying, and a board that lies is worse than no board.

---

## Standup — the Log at the bottom of STATUS.md

> The purpose of the standup is to synchronize everyone on the team with each other and the work to
> be done. — Curriculum 200, *Stand-Ups*

Synchronization is the point; the meeting is just one implementation of it, and it's the wrong one
for a team that doesn't share a timezone or a memory. Here, **the Log is the standup**, and the
question-driven format survives intact — every Log line answers the same three questions:

```
- 2026-08-06 — Kirito (via Claude) — Finished T014 (parser handles nested blocks, tests green).
  Next: T015 error recovery. Blocked on: nothing.
```

The Curriculum's don'ts translate directly:

- **DO put a clock on it.** A Log entry is two or three lines. If it needs more, it's a handoff
  document, not a Log entry.
- **DO keep it question-driven.** Done / next / blocked. Not a narrative of everything you tried.
- **DON'T problem-solve in it.** A blocker gets *named* in the Log and *worked* in the PR or the
  design doc. "Blocked on: the schema for X is undecided" is a standup line; three paragraphs
  proposing schemas is not.
- **DON'T micromanage.** The Log records what happened, not an audit of who was slow.

**Every session ends with a Log line.** An AI that finishes work without writing one has left the
next session blind, and that is not "done" ([AGENTS.md](../AGENTS.md) §5).

---

## Showcase — a green `main` you can actually run

> State what you were trying to achieve with that iteration. Then move on to showing what your code
> does. — Curriculum 200, *Iteration Showcases*

The kit's promise that "`main` is always green and demo-ready" is a showcase claim, and it's worth
testing rather than assuming. At a natural checkpoint — a phase completed in the PLAN.md timeline, or
a story finished end to end:

1. Clone the repo fresh, into a new directory. Not your working copy — your working copy has
   uncommitted files, a warm cache, and a `.env` nobody else has.
2. Follow your own README from the top.
3. Run the golden path.

If that fails, `main` was never demo-ready; it was *your machine* that was demo-ready. The gap is
almost always an undocumented setup step or an uncommitted file, and it is much cheaper to find at a
checkpoint than in front of someone.

Record the outcome in STATUS.md under **What's built so far** — stated as what a person can now do,
not which files exist:

```
- A user can upload a screenplay and get a scene breakdown back. (Stories S1, S2; phases 0-2.)
```

---

## Retrospective — a section in STATUS.md, at each phase boundary

> Every person did the best they could do, given the circumstances and the information that was known
> at the time. — Curriculum 200, *Iteration Retrospectives* (the prime directive)

That directive is doing real work on a project like this: when a lane comes back wrong, the useful
question is what the design doc failed to say, not who to blame — and when the lane was built by an
AI, blame is especially useless, since an AI will agree it was wrong and then make the same mistake
next session. Only a change to the written process changes the outcome.

Three parts, ten minutes, at each phase boundary:

1. **Gather.** What actually happened? Read the Log, the merged PRs, the tasks that slipped.
2. **Analyse.** Why? Look for the *system* cause: a design doc that skipped a diagram, a task whose
   `Done:` wasn't observable, a contract two lanes read differently.
3. **Commit.** One change, written down where it will be read again — a rule in AGENTS.md, a line in
   the DESIGN-DOC template, a new check in `scripts/gate.sh`. A commitment that isn't in a file the
   next session reads has not been made.

That last point is why this kit exists in the form it does. Every rule in AGENTS.md is a retrospective
commitment from a project that got it wrong once — and [the gate](git-workflow.md#the-gate) is the
form a commitment takes when you want it enforced rather than remembered.

---

## Where this shows up

| Ritual | Artifact | Cadence |
|---|---|---|
| Backlog | SPEC.md (stories) + TASKS.md (tasks) | continuous |
| Taskboard | STATUS.md § Current focus | every task transition |
| Standup | STATUS.md § Log | every session, without exception |
| Showcase | fresh clone + golden path | each phase boundary |
| Retrospective | STATUS.md § Retrospectives | each phase boundary |
