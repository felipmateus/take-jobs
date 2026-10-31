---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 357
severity: medium
author: claude-code
provider_ref:
---

# Issue 005: Run totals derive from results, which are empty in list views

## Review Comment

**Problem.** In Core Interfaces, `CollectionRun.results` is "empty while running and in list views" (line 357), and `CollectionRun.totals` is a property that sums `results` (line 360). `CollectionRunRepository.list` returns `Page[CollectionRun]` (line 388). So every run returned by `GET /collection-runs` would report `totals = {0, 0, 0}`. That contradicts:
- `_dx.md` lines 221–239, where the list example shows non-zero totals;
- Key Decisions (line 695): "list views read totals with an aggregate subquery". The domain type has nowhere to carry those totals.

E2E-001 ("`GET /collection-runs` → 1 item whose `totals` equal the CLI JSON's") would fail against an implementation that follows the interfaces, so the implementer has to invent the fix.

UT-017 tests `totals` only from `results`.

**Suggested fix.** Choose one representation and update Core Interfaces:
- (a) Make `totals: RunTotals` a stored field of `CollectionRun`. The repository fills it from the aggregate subquery in `list` and `get`, and the domain keeps a helper `RunTotals.from_results(...)` that `complete_run` uses.
- (b) Add a separate `CollectionRunSummary` type for list views.

Then add an IT-006 case: `list()` returns non-zero totals for a finished run with results.

## Triage

- Decision: `VALID`
- Notes: Root cause: totals was a property derived from results, which are empty in list views.
- Fix applied (spec-only round, no code exists): _spec.md Core Interfaces: RunTotals.from_results, CollectionRun.totals stored field filled by repository aggregate; UT-017 updated; IT-006 case added.
- Verified (round 2): `CollectionRun.totals: RunTotals` is a stored field filled by the repository aggregate; `RunTotals.from_results` exists; UT-017 and the new IT-006 case (list returns non-zero totals with `results == ()`) cover it; `_dx.md` running-run zero totals is consistent.
