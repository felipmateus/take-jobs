---
status: completed
title: "Task 8: Scheduler: daily cron, startup catch-up and signal forwarding"
type: feature
complexity: high
---

# Task 8: Scheduler: daily cron, startup catch-up and signal forwarding

## Overview

This task delivers `take-jobs scheduler`, the process that keeps the job bank fresh with no manual step:
- it waits for the database;
- it registers the daily cron in standard-cron semantics;
- it collects immediately when the store is empty or no run finished in the last 24 hours;
- it forwards SIGTERM and SIGINT to a running collector, including during the startup run.

## Shippable Outcome

- **Outcome:** `uv run take-jobs scheduler`
  - installs its shutdown handler first;
  - pings the database with backoff, for up to 60 seconds;
  - logs `scheduler_started`;
  - applies rule 14, launching `python -m take_jobs collect --trigger startup` when it applies;
  - runs `--trigger scheduled` on `SCRAPE_CRON` in `SCRAPE_TIMEZONE`.

  A stop forwards SIGTERM to the running collector and exits `0` as soon as the collector exits.
- **Verify in this task:** UT-080–UT-089.
- **Integration verification:** MAN-001 in task_09 checks this behavior in Docker Compose.

## Requirements

- **Seams:** `take_jobs.cli.scheduler` exposes `wait_for_database`, `run_startup`, `configure_scheduler`, `make_shutdown_handler` and `run_scheduler`, plus `take_jobs.cli.runner` with the `CollectionRunner` protocol and `SubprocessCollectionRunner`, exactly as in `_spec.md` › Core Interfaces.
- **Start-up order:** handler first, then wait for the database, then configure, log, `run_startup` and `start()` (`_spec.md` › Scheduler start-up).
- **Runner:**
  - `Popen` with `shell=False`;
  - waiting is done by polling `poll()`, never a blocking `wait()`;
  - `terminate_current` sends SIGTERM, polls for up to `wait_s`, then kills (Safety Invariant 6; review round 4, issue 002).
- **APScheduler job:**
  - `CronTrigger.from_crontab(to_standard_crontab(SCRAPE_CRON), timezone=…)`, `max_instances=1`, `coalesce=True`, `misfire_grace_time=3600`;
  - it is the only job.
- **Main command:** `take-jobs` gains the `scheduler` subcommand, and `--help` lists both commands (UT-086).

## Subtasks

- [x] 8.1 Write `cli/runner.py`: `CollectionRunner`, `SubprocessCollectionRunner`.
- [x] 8.2 Write `cli/scheduler.py`: the seams and `run_scheduler`.
- [x] 8.3 Add the `scheduler` subcommand in `cli/main.py`.
- [x] 8.4 Write the unit tests, including UT-089 with a real short-lived child.

## Implementation Details

### Relevant Files

- `src/take_jobs/cli/{runner,scheduler}.py` — new.
- `src/take_jobs/cli/main.py` — add the subcommand.
- `tests/unit/cli/test_scheduler.py`, `tests/unit/cli/test_runner.py`, `tests/support/sigterm_child.py` — new.

### Dependent Files

- `src/take_jobs/application/services.py` (`startup_reason`, `ping`; task_05) and `cli/main.py` (task_06).

### Related ADRs

- [ADR-004: APScheduler container launching the collector as a subprocess](adrs/adr-004.md).

## Deliverables

- The scheduler command and runner.
- Passing unit tests.

## Tests

- [x] UT-080–UT-083 — startup rule, flag, cron job configuration.
- [x] UT-084 — runner polling and `terminate_current`.
- [x] UT-085 — database wait with backoff.
- [x] UT-086 — `python -m take_jobs --help`.
- [x] UT-087, UT-088 — the shutdown handler and the handler-first ordering.
- [x] UT-089 — a stop during the startup run returns promptly with a real child.

## Success Criteria

- No unit test blocks; UT-089 finishes within 3 seconds of its signal.
