---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/adrs/adr-004.md
line: 23
severity: low
author: claude-code
provider_ref:
---

# Issue 016: SCRAPE_CRON day-of-week differs from cron under from_crontab

## Review Comment

**Problem.** `_dx.md` line 324 documents `SCRAPE_CRON` as a "5-field cron", and ADR-004 parses it with APScheduler 3.x `CronTrigger.from_crontab`. In APScheduler 3.x the day-of-week field of `from_crontab` is Monday-based (0 = Monday), not standard cron's Sunday-based numbering. A maintainer who writes a standard cron expression with a weekday number gets the wrong day. The default `0 6 * * *` is unaffected.

**Runtime evidence** (APScheduler 3.11.3):
```
'0 6 * * 0' next from Fri 2026-10-30 -> Mon 2026-11-02     # standard cron: Sunday
```

**Suggested fix.** Choose one:
- document in `_dx.md` and `.env.example` that weekday fields must use names (`sun`, `mon`, …), and have the validator reject numeric day-of-week values;
- translate numeric day-of-week values before calling `from_crontab`, and add a UT-025 case for `0 6 * * 0` → Sunday.

## Triage

- Decision: `VALID`
- Notes: Root cause: APScheduler from_crontab numbers day-of-week from Monday.
- Fix applied (spec-only round, no code exists): _spec.md to_standard_crontab and Config Lifecycle; ADR-004; _dx.md SCRAPE_CRON docs; US-020.EC-5; UT-019, UT-083.
- Reopened (round 2, 2026-10-30): `to_standard_crontab` (numbers to names) fixes single days and ranges that do not start on Sunday. Ranges that start on Sunday still fail, because APScheduler's day names are Monday-first. Runtime, APScheduler 3.11.3, `CronTrigger.from_crontab` on the rewritten expressions:
  - `0 6 * * 1-5` → `mon-fri`: ok.
  - `0 6 * * 5-7` → `fri-sun`: ok.
  - `0 6 * * 0-4` → `sun-thu`: `ValueError: The minimum value in a range must not be higher than the maximum`.
  - `0 6 * * 0-6` → `sun-sat`: the same error.
  So the valid standard crons `0-4` (Sun–Thu) and `0-6` are rejected as a configuration error (exit `2`), against `_dx.md` › Config ("standard 5-field cron; day-of-week 0 or 7 = Sunday").
  Fix: have `to_standard_crontab` split a range that starts at 0 into a list (`0-4` → `sun,mon-thu`), or expand day-of-week ranges into explicit name lists. Add the `0-4` and `0-6` cases to UT-019.
- Round-2 fix: to_standard_crontab expands the day-of-week field (numbers 0-7, names, ranges, lists, steps) into an explicit Sunday-first list of names, so no emitted range can wrap. UT-019 now covers 0-4, 0-6, 5-7, */2 and sun-thu; ADR-004 and Config Lifecycle updated.
- Verified (round 3, 2026-10-30): APScheduler 3.11.3 `CronTrigger.from_crontab` accepts every non-error UT-019 output (`sun`, `mon,…,fri`, `sun,mon,tue,wed,thu`, the 7-name list, `sun,fri,sat`, `sun,tue,thu,sat`). From Fri 2026-10-30 12:00 America/Sao_Paulo, `sun` and `sun,mon,tue,wed,thu` both fire next on Sun 2026-11-01 06:00, as UT-019 states. A never-started `BackgroundScheduler` exposes the job's trigger, `max_instances`, `coalesce` and `misfire_grace_time`, so UT-083 can be written as specified.
