# `Tokelo` — Handoff

> Copy this to `docs/HANDOFF.md`, fill it in, then set the `## ⇄ HANDOFF` block at the top of
> [STATUS.md](STATUS.md) to `ACTIVE` and point it here.
>
> **Write this while you still have budget left.** A handoff written after you run out is
> worthless. Ten minutes spent here saves the incoming session an hour of rediscovery.

**Written:** YYYY-MM-DD · **Branch:** `<branch>` · **By:** `<name>` (via `<tool>`)

---

## 1. What is done

A table, not prose. Be explicit about what is **not** started — an incoming AI cannot tell
"deliberately skipped" from "forgotten" unless you say so.

| Area | Status |
|---|---|
| | ✅ / ⚠️ partial / ❌ not started |

**How to verify the current state is green:** `<the exact command, e.g. pytest -q → 23 passed>`

## 2. Decisions already locked (do not relitigate)

The single highest-value section. Every decision re-opened is budget burned twice.

| Decision | Choice | Why |
|---|---|---|
| | | |

**Non-negotiables still in force:** `<pull from PLAN.md>`

## 3. Environment — how to run it

Exact commands, not descriptions. Include anything non-obvious about this machine: where the
venv lives, tools installed outside the package manager, env vars that must be set, ports.

```bash
```

## 4. Verified facts

Things you confirmed by actually running or fetching something — API shapes, IDs, version
numbers, response formats. **This is the expensive part to rediscover**, so write down what
you learned and how you confirmed it.

| Fact | Value | How confirmed |
|---|---|---|

## 5. Corrections

Anything you previously reported that turned out to be wrong. State it plainly — an
uncorrected error propagates into every downstream decision.

- **Previously said:** … **Actually:** … **Impact:** …

## 6. Next steps, in order

Numbered and specific enough to act on without re-planning. "Wire up auth" is not a step;
"add `POST /api/session` returning a signed cookie, mirroring `GET /api/me`" is.

1.

## 7. Gotchas

Traps the next session will otherwise fall into — especially **bugs already fixed that must
not be reintroduced**, and anything where the obvious approach is the wrong one.

-

## 8. Open questions

Things you could not resolve and deliberately left. Say what you would have done next.

-
