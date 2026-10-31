---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 681
severity: medium
author: claude-code
provider_ref:
---

# Issue 009: O5 success-rate query ignores runs that failed as a whole

## Review Comment

**Problem.** PRD O5 is the share of site × term combinations completed successfully over 7 days, "as reported by the collection run history". The spec computes it from `collection_run_results` only (`_spec.md` line 681). But several whole-run failures write **no result rows**:
- a crawl crash: `fail_run` gives `results == ()` (UT-063);
- an interrupted or orphaned run (rule 13);
- an ingest failure (see issue 002);
- a scheduled run refused with exit 3, which "records nothing".

Each of these drops 24 combinations from the denominator. A week in which 3 of 7 daily runs crashed can still report 100%. O5 is the PRD's reliability objective, so the metric as specified can certify a failing system.

**Suggested fix.** Define O5 so that every combination expected in a failed run counts as failed. Either:
- `fail_run` and `mark_interrupted` write one `failed` result row per source × term, with the run error; or
- the README query computes the denominator as `runs × sources × terms` per day, and counts days with no run as failures.

Pin the query in the spec, and add an IT that seeds a crashed run and asserts the query result.

## Triage

- Decision: `VALID`
- Notes: Root cause: the O5 denominator came from result rows, which whole-run failures do not write.
- Fix applied (spec-only round, no code exists): _spec.md collection_runs.expected_combinations column, pinned O5 SQL in Monitoring; start_run(expected_combinations); IT-014.
- Verified (round 2): `collection_runs.expected_combinations`, `start_run(expected_combinations)`, the pinned O5 SQL and IT-014. Ran the query on postgres:16 with the IT-014 seed: `success_rate_pct = 71.4` (120/168), as specified. A separate defect in the query's date window is tracked as reviews-002/issue_002.
