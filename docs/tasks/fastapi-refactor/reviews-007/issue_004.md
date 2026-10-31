---
provider: manual
pr:
round: 7
round_created_at: 2026-10-31T00:56:07Z
status: resolved
file: tests/integration/test_o5_query.py
line: 30
severity: low
author: claude-code
provider_ref:
---

# Issue 004: IT-014(b) fails if São Paulo midnight falls during the test

## Review Comment

Each `_seed_run` call runs in its own `engine.begin()` transaction, and `_success_rate` runs in yet another one. PostgreSQL's `now()` is the **transaction** start time, so the seeds and the query compute "today" from up to nine different clocks: the `NOON` expression and the `days` CTE in `metrics.sql`. Effect of an `America/Sao_Paulo` date change (03:00 UTC):

- **(b)** If the change falls between the last seed and the query, the window shifts by one day. Seeded D-7 drops out, and the new D-1, the seeding day, has no finished run. The result is 6×24/168 = **85.7, not 100.0**, and the test fails. The `running` variant fails the same way.
- **(a)** A change after all seeds is harmless: the window and the seeds shift together, and 120/168 stays 71.4. A change *between two seed statements*, however, puts two runs on one day and leaves a gap, which changes the result.

The exposure is the test's run time (tens of milliseconds), so the flake is rare. It is still deterministic and cheap to remove, and the memory note "could in theory flake" leaves it unfixed.

Suggested fix: seed and query on **one connection inside one transaction**, so `now()` is identical for every statement. For example, pass a single `connection` from one `engine.begin()` into `_seed_run` and `_success_rate`, and roll back at the end. `metrics.sql` stays untouched, so UT-112's "README embeds it verbatim" check is unaffected.

## Triage

- Decision: `VALID`
- Notes:
  - Valid: each `_seed_run` and `_success_rate` ran in its own transaction, so `now()` (transaction start) and the `NOON` expressions could straddle São Paulo midnight (03:00 UTC) and shift the window by a day (85.7 instead of 100.0 in (b)).
  - Fix: `tests/integration/test_o5_query.py` seeds and queries on one `engine.connect()` connection inside one transaction that is never committed (rolled back on exit), so `now()` is identical for every statement. `metrics.sql` is untouched, so UT-112 (README embeds it verbatim) is unaffected. Owning suite: IT-014 (a, b, and the `running` variant), run in the full gate.
- Verified (round 8): `tests/integration/test_o5_query.py` now seeds and queries on one `engine.connect()` connection; SQLAlchemy autobegins a single transaction, and closing the connection rolls it back, so `now()` is identical for every statement. `metrics.sql` is untouched. Ran `pytest tests/integration/test_o5_query.py` against Docker -> 3 passed (IT-014a, IT-014b none/running).
