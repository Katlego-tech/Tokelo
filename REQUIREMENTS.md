# `tokelo` — Requirements

**Spec:** [SPEC.md](SPEC.md) · **Tasks:** [TASKS.md](TASKS.md) · **Gates:** [GATES.md](GATES.md)

> SPEC.md tells the story; this file is the list the gate checks. `scripts/realm/realm req-lint`
> checks every entry, and `scripts/realm/realm trace` checks each requirement's links to its tasks,
> commits, tests and releases (ISO/IEC/IEEE 29148; Secret Realm DESIGN.md §7).

---

## How requirements are written here

**Four levels, each with its own ID prefix.** IDs are never reused.

| Level | Prefix | Answers | Parent |
| --- | --- | --- | --- |
| Business | `BR-nnn` | why the system exists | none |
| Stakeholder | `SR-nnn` | what each stakeholder needs from it | a `BR-` (required in the assured tier) |
| Software | `REQ-nnn` | what the software shall do | an `SR-` or a `BR-` (always required) |
| Quality (ISO/IEC 25010) | `NFR-nnn` | how well, as a measured target | any level (required in the assured tier) |

**States:** proposed → approved → implemented → verified → released → deprecated → retired, or
withdrawn. A requirement is **approved** only when:
- its quality checklist ticks all nine characteristics: unambiguous, necessary, feasible,
  verifiable, singular, implementation-free, correct, complete, consistent
- a task names it (`Req:` in TASKS.md)
- a test names it, written first

`implemented` also needs one of its tasks done; `released` needs a release record in
`docs/releases/` that lists it.

**How a test names its requirements** (the trace reads all three):
- **Python:** `@pytest.mark.req("REQ-012")`. Register the marker once in your pytest
  configuration: `markers = ["req(*ids): the requirements this test verifies"]`.
- **JS/TS:** the test title starts with the IDs: `it("[REQ-012] refuses a launch into a full world", …)`.
- **Anything else** (k6 scripts, shell tests): a comment line `req: NFR-003`, in a file under a
  `tests/`, `e2e/`, `perf/` or similar folder.

**Verify by** is one of `test`, `analysis`, `inspection` or `demonstration`. It's required on every
`REQ-` and `NFR-`, and in the assured tier on every level, fixed before the requirement is built
(the V-Model's pairing).

### Entry format

```markdown
### REQ-012 — Refuse a launch into a full world
- Level: software · Parent: SR-004 · State: approved
- Statement: When no cell is free, the system shall refuse the launch and reply "no more space".
- Verify by: test (acceptance)
- Quality: unambiguous ✓ necessary ✓ feasible ✓ verifiable ✓ singular ✓ implementation-free ✓
  correct ✓ complete ✓ consistent ✓

### NFR-003 — API latency
- Characteristic (ISO/IEC 25010): performance efficiency · Parent: SR-004 · State: approved
- Target: p95 < 200 ms for GET /api/robots at 50 requests/second
- Verify by: test (performance)
- Measured by: perf/robots.js (k6) in the release pipeline
- Quality: unambiguous ✓ necessary ✓ feasible ✓ verifiable ✓ singular ✓ implementation-free ✓
  correct ✓ complete ✓ consistent ✓
```

An NFR's **Target** needs a bound (`<`, `≤`, at most, within…) on a number with a unit, and it
names the tool that measures it.

---

## Operational concept (OpsCon)

<!-- Who operates the system, where and under what conditions: its users and their roles, the
     environments it runs in, a normal day, a bad day (load peaks, outages), and what "working"
     looks like to each of them. Required once any requirement is approved. -->

## Business requirements

<!-- ### BR-001 — … -->

## Stakeholder requirements

<!-- ### SR-001 — … -->

## Software requirements

<!-- ### REQ-001 — … -->

## Quality requirements

<!-- ### NFR-001 — … -->
