---
provider: manual
pr:
round: 2
round_created_at: 2026-10-30T20:39:57Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 814
severity: medium
author: claude-code
provider_ref:
---

# Issue 002: O5 query counts today before its run, capping the rate at 85.7%

## Review Comment

**Problem.** The pinned O5 query (`_spec.md` › Monitoring, lines 812–825, added for round 1 issue 009) builds its window as `generate_series(today − 6, today)`. It counts any day "with no finished run" as `:expected` failed combinations. Today has no finished run from local midnight until the daily run ends, about 06:10 with the default `SCRAPE_CRON`. While today's run is `running`, the query also excludes it (`WHERE c.status <> 'running'`). A query run in that window therefore counts today as 24 of 24 failed, and caps the result at 6/7 = 85.7%, even when every run of the previous six days fully succeeded. O5's target is ≥ 95%.

**Runtime evidence** (postgres:16, the spec's `collection_runs`/`collection_run_results` DDL, the query verbatim with `:tz = America/Sao_Paulo` and `:expected = 24`):
```
IT-014 seed (5 ok days, 1 crashed run, 1 day without a run)   -> 71.4   (as specified)
6 previous days all 24/24 success, today's run not yet finished -> 85.7
same, with today's run in status 'running'                      -> 85.7
```

MAN-002 ("after 7 days of operation, run the README's success-rate SQL query") and the README copy of the query (UT-112) inherit this. Whether O5 passes then depends on the time of day the query runs. IT-014 passes either way, because it seeds "1 day has no run" without saying which day.

**Suggested fix.**
- Measure the 7 **complete** days ending yesterday: `generate_series(today − 7, today − 1)`. Alternatively, include today only when a run has started today and is no longer `running`.
- Update the bullet "A day of the last 7 with no finished run…" to match.
- Pin the IT-014 seed so the day without a run is a past day.
- Add an IT-014 case: six perfect past days, and today without a finished run, gives 100.0.

## Triage

- Decision: `VALID`
- Notes: Root cause: the O5 window included today, which has no finished run until the daily run completes.
- Fix applied (spec-only round, no code exists): _spec.md Monitoring: the window is the 7 complete days ending yesterday (generate_series(today-7, today-1)), and the bullet text is updated. IT-014 parametrized: (a) the seeded days are pinned to D-1..D-7, giving 71.4; (b) seven perfect past days with today unfinished or running give 100.0.
- Verified (round 3, 2026-10-30): the window is now `generate_series(today − 7, today − 1)`, the bullet text matches, and IT-014 pins (a) D-1..D-7 → 71.4 and (b) seven perfect past days with today unfinished or running → 100.0. Docker is unavailable this round, so the query was not re-run; the change only moves the series bounds of the query that round 2 ran on postgres:16.
