---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 93
severity: medium
author: claude-code
provider_ref:
---

# Issue 004: Missed-run recovery (rule 15) can't happen with in-memory APScheduler

## Review Comment

**Problem.** Rule 15, US-001.EC-3 and the ADR-004 risk (line 63) all promise: "If the scheduler container is down at 06:00, the run is skipped unless it is back within 1 hour." The design is a `BlockingScheduler` with the default in-memory job store, re-created on every start. On a restart, APScheduler 3.x computes the job's first fire time from *now*. `misfire_grace_time` only applies to a fire time the running scheduler already knew about, so a slot missed while the container was down is never fired.

**Runtime evidence** (APScheduler 3.11.3, job configured exactly as UT-083 specifies):
```
first fire time computed on (re)start at 06:30 -> 2026-11-01 06:00:00-03:00
```
That is, a restart at 06:30 on 10-31 skips 10-31 entirely.

**Test gap.** UT-083 and the coverage-matrix row for US-001.EC-3 (`_tests.md` line 42) assert only the `misfire_grace_time=3600` and `coalesce=True` values ("firing itself is APScheduler's tested behavior"). The test passes, but the contracted behavior never happens.

**Suggested fix.** Choose one option and record it in ADR-004:
- (a) Add explicit catch-up logic at scheduler start: if the previous cron slot is within 1 h of now and no run has `started_at` at or after that slot, launch a `scheduled` run. Add a UT with a fake clock at 06:30, and another at 07:30, that asserts no catch-up.
- (b) Re-word rule 15, US-001.EC-3 and the ADR-004 risk to the real behavior: a missed slot is skipped, and only an in-process delay (such as host sleep) within 1 h is recovered.

## Triage

- Decision: `VALID`
- Notes: Root cause: the in-memory APScheduler job store never replays slots missed while down. User decision (2026-10-30): collect at scheduler start when the store is empty OR no run finished in the last 24 h.
- Fix applied (spec-only round, no code exists): PRD FR-06 amended; _spec.md rules 14-15, startup_collection_reason, CollectionRunRepository.latest_finished, CollectionService.startup_reason; SCRAPE_ON_EMPTY_DB renamed SCRAPE_ON_START; ADR-004 revision and risks; US-001.EC-3, US-004.AC-4; UT-018, UT-067, UT-080, UT-081.
- Reopened (round 2, 2026-10-30): the user's decision is implemented in rules 14–15, `startup_collection_reason`, `latest_finished`, `SCRAPE_ON_START`, ADR-004, US-001.EC-3, US-004.AC-4, UT-018/067/080/081 and the amended FR-06. It is not carried through every artifact:
  - `_user_stories.md` US-019.EC-3 (line 346) still says a second `docker compose up` on an existing volume runs "no startup collection … if jobs exist". Under rule 14 it does run when the latest finished run started more than 24 h ago.
  - `_tests.md` MAN-001 (line 472) expects "the startup run skipped" on the second `up`, without the 24 h condition.
  - ADR-004 Context (line 15) still states the pre-amendment FR-06 ("when the database is empty").
  - ADR-004 Risks bullet 2 (line 75) is self-contradictory: a restart more than 24 h after the previous finished run cannot happen on a day whose 06:00 run already finished.
  Fix: reword US-019.EC-3 and MAN-001 to "no startup collection if jobs exist **and** a run finished with a start in the last 24 h"; update the ADR-004 Context and that risk.
- Round-2 fix: US-019.EC-3 and MAN-001 reworded to the 24 h rule; ADR-004 Context states the amended FR-06; the self-contradictory ADR-004 risk is replaced by the overlap case (database guard, exit 3). Matrix row US-019.EC-3 now cites UT-080/UT-081.
- Verified (round 3, 2026-10-30): US-019.EC-3 (line 346) and MAN-001 now state the 24 h rule; ADR-004 Context quotes the amended FR-06; the self-contradictory risk is gone; the US-019.EC-3 matrix row cites UT-080/UT-081. No artifact still promises a skip based on stored jobs alone.
