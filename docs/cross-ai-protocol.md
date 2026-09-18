# Cross-AI protocol

Multiple AI assistants operate on one repo — potentially more than one per person (a primary
implementation AI plus a faster "accelerator" assistant, or simply different people using different
tools). This protocol keeps them from colliding.

> 📝 **Customize:** list the actual tools/pairings in play, e.g.:
> - `<Person A>` = `<primary AI>` (entry point [CLAUDE.md](../CLAUDE.md))
> - `<Person B>` = `<primary AI>` + `<Gemini/other>` (entry point [GEMINI.md](../GEMINI.md))
>
> The rules below are identical **no matter how many tools are in play or which ones** — that's the
> point of routing everything through AGENTS.md instead of writing per-tool rules.

## The shared brain (read in this order, every session)

| File | Role |
| --- | --- |
| [../STATUS.md](../STATUS.md) | The live state. Done / in-progress / next / lanes / log. |
| [../AGENTS.md](../AGENTS.md) | The rules every assistant must follow. |
| [../TASKS.md](../TASKS.md) | The single task list every AI and human works from. |

No other channel is authoritative. If it's not in these files, it didn't happen.

> **Using an assistant that doesn't auto-read repo files?** At the start of a session, paste
> `AGENTS.md` + the current `STATUS.md` into it. That's all any assistant needs to participate
> correctly — see [AI_ENTRYPOINT.template.md](../AI_ENTRYPOINT.template.md).

## Session start handshake (every AI, every session)

0. **Check the `## ⇄ HANDOFF` block at the top of [../STATUS.md](../STATUS.md) first.**
   If its status is `ACTIVE`, a handoff is in play: stop, read the linked handoff document
   end to end, and resume from its "Resume at" pointer. Do not start anything else, and do
   not re-plan work the outgoing session already decided. See [Handoffs](#handoffs) below.
1. Read STATUS.md → AGENTS.md → TASKS.md.
2. Look at the **Current focus** lane table in STATUS.md. Is someone (or another AI) already on the
   task you want?
   - **Yes** → pick a different unclaimed task, or coordinate in STATUS.md first.
   - **No** → add a row claiming the lane: `lane:<name> | <you> | <your AI> | in progress`.
3. Do the work (with tests).
4. **Session end:** tick the task in TASKS.md, update STATUS.md sections, add a dated Log line.

## Core rules

### Single-writer-per-task

A task in TASKS.md has exactly **one owner at a time**. Before starting, claim it in STATUS.md (your
name + the task id). Two assistants must never edit the same task's files concurrently. If a task is
already claimed, pick another.

### Lane labels

Work is organized into **lanes** matching the project's real modules/features (not arbitrary — pick
names that match [docs/project-structure.md](project-structure.md)). Branches use the lane
(`feat/<lane>`) and commits carry the scope (`feat(<lane>): T0xx ...`). Lanes keep parallel work in
disjoint file regions — see [git-workflow.md](git-workflow.md).

**One standing exception:** lanes that produce user-facing UI are assigned to Claude by
default, because the `frontend-design` skill only loads for Claude and a visual identity
degrades fastest when several hands re-decide palette and spacing in turn. See
[AGENTS.md](../AGENTS.md) §1 "Frontend work goes to Claude".

### Read-before-write

Always **pull latest and read STATUS.md + AGENTS.md before touching anything.** State changes
between sessions and between assistants. Never write from a stale view of the board.

### Keep STATUS.md current

STATUS.md is only useful if it is true. Update it when you **claim**, **finish**, or **hand off** a
task, and when you hit a blocker. A finished task gets its checkbox ticked in TASKS.md and its line
cleared/updated in STATUS.md.

## Handoffs

A **handoff** is when one AI stops mid-stream and another continues the same work — usually
because a usage limit is about to be hit, a session is being closed, or the work needs a
different tool. It is a normal, expected part of the cycle, not an exception.

The failure mode a handoff exists to prevent is the incoming AI **silently re-deriving context
and re-litigating decisions the outgoing one already made** — re-choosing the stack, re-reading
the whole codebase, re-discovering an API's shape. That wastes the very budget the handoff was
meant to protect.

### The signal

`STATUS.md` is already the mandatory first read for every session, so the handoff signal lives
there — at the very top, as a `## ⇄ HANDOFF` block. There is no second mechanism to remember
and nothing to poll. `ACTIVE` means a handoff is in play; `none` means normal operation. The
block stays in place even when dormant, so its absence is never ambiguous.

### Raising a handoff (outgoing AI)

Do this **while you still have budget left** — a handoff written after you run out is worthless.

1. Commit and push everything, even if incomplete. Unpushed work cannot be handed off.
2. Copy `HANDOFF.template.md` to `docs/HANDOFF.md` and fill it in. At minimum:
   - **What is done**, and what is explicitly *not* started
   - **Decisions already locked**, with the reason — so they are not reopened
   - **How to run it**: exact commands, environment quirks, where the venv/toolchain lives
   - **Verified facts** the incoming AI would otherwise have to rediscover (API responses,
     IDs, version numbers) — these are the expensive part
   - **Next steps, in order**, specific enough to act on without re-planning
   - **Gotchas**, especially bugs already fixed that must not be reintroduced
   - **Corrections** to anything you previously reported wrongly, stated plainly
3. Set the `## ⇄ HANDOFF` block in STATUS.md to `ACTIVE`, fill in the branch and the
   "Resume at" pointer, and name the specific first action.
4. Add a dated Log line in STATUS.md.
5. Leave your lane row in the focus table as `paused — handed off` rather than deleting it.

### Picking up a handoff (incoming AI)

1. Read `docs/HANDOFF.md` completely before touching a file.
2. **Verify before trusting.** A handoff records what was true when written. If it names a
   file, function, flag or identifier, confirm it still exists — then proceed.
3. Claim the lane in STATUS.md under your own name and AI.
4. Set the `## ⇄ HANDOFF` block back to `🟢 none` **only once you are actually committing
   work**, not on first read. A half-picked-up handoff should still read `ACTIVE` to the
   next session.
5. Add a Log line recording that you picked it up.

### Rules

- **One active handoff at a time.** If one is already `ACTIVE`, resolve it before raising another.
- **A handoff is not a plan.** It records reality — what is done, what is known, what is next.
  Speculative design belongs in PLAN.md.
- **Never silently drop a handoff.** If you decide not to continue the outgoing AI's approach,
  say so explicitly in the Log with the reason. Do not just start something else.
- **Keep it current or kill it.** A stale `ACTIVE` handoff is worse than none, because it sends
  the next session down a path that no longer exists.

## Who ratifies changes

There is no automated "system of record." Changes to SPEC.md, PLAN.md, and TASKS.md land like any
other change — via a PR, reviewed according to the review mode in [AGENTS.md](../AGENTS.md) §4.
`<the project leader>` has the final call on
scope and the non-negotiables.

## Conflict recovery

If two changes collide (merge conflict, or both edited STATUS.md):
1. Don't force-push over the other person's/AI's work.
2. Resolve on the branch; keep both sets of Log entries.
3. If a task got worked twice, keep the better implementation, note the duplication in the Log so you
   learn from it.

## Collision avoidance in one line

Pull → read STATUS.md/AGENTS.md → claim a task (single writer) → work in your lane branch → update
STATUS.md → PR into green `main`.
