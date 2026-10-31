# task_08 memory

## Outcome
Completed. `take-jobs scheduler` works: handler first, database probe with backoff, cron job, `scheduler_started`, rule 14 startup run, loop. Source: `src/take_jobs/cli/scheduler.py` (new), `src/take_jobs/cli/main.py` (subcommand, metavar `{collect,scheduler}`), `src/take_jobs/cli/runner.py` (unchanged: task_06's runner already matched the spec). Tests: `tests/unit/cli/test_scheduler.py` (22: UT-080-083, 085-088 plus extras), `tests/unit/cli/test_runner.py` (7: UT-084, UT-089), `tests/support/sigterm_child.py`. Full suite 384 passed.

## Decisions
- `DatabaseUnavailableError` lives in `cli/scheduler.py` (the spec names it but defined it nowhere). `wait_for_database` retries on any `Exception`; `SystemExit` from the handler passes through. Backoff 1, 2, 4, 8, 10, 10 ...; it raises at the first failed attempt after the slept delays reach `max_wait_s` (65 s of delays with the default 60).
- `run_startup`: flag off -> logs `startup_collection_skipped reason=disabled` and does not touch the database; reason found -> logs `startup_collection reason=...` then `runner.run(STARTUP)`; else `startup_collection_skipped reason=recent_run_exists`. A non-zero collector exit never stops the scheduler.
- `configure_scheduler` adds one job (id `scheduled_collection`) whose function logs `collection_triggered` and calls `runner.run(SCHEDULED)`. The next fire time in `scheduler_started` is computed from a second `CronTrigger` built by the same helper and `deps.clock.now()` (the pending job has no `next_run_time` before `start()`).
- `make_shutdown_handler` never logs (it can interrupt the main thread inside logging); `run_scheduler` logs `scheduler_stopped` while `SystemExit` propagates. `run_scheduler` restores the original SIGTERM/SIGINT handlers in `finally`, so tests leave no handler behind.
- UT-089: `sys.executable` is monkeypatched to a tmp `sh` launcher that `exec`s `tests/support/sigterm_child.py`, so the real runner (real `Popen`, real polling) runs a real child and the real SIGTERM is sent to the test process from a timer thread once the child's ready file exists (no fixed sleep, no race with the child's handler). It asserts `SystemExit(0)` within 3 s of the signal, no `kill()` (the thread wraps `child.kill`), child exit code 4, and `runner.current is None`; the child has a 20 s self-timeout and the test kills it in `finally`.
- Runner unit tests patch `take_jobs.cli.runner.time` with a virtual clock (`sleep` advances `monotonic`), so the 25 s kill case runs instantly; `FakePopen.wait` raises to prove polling.

## Evidence
`uv run ruff format --check`, `ruff check`, `lint-imports` (8 kept) clean; `uv run pytest -q` 384 passed (108 s); `tests/unit/cli/test_runner.py` three runs in a row 7 passed (about 2 s); no stray process and no container left (`docker ps -a` shows only the user's exited `mrt-local-pg`). Manual: `python -m take_jobs scheduler` against a closed-port `DATABASE_URL` logs `startup_probe_failed` and exits 0 on SIGTERM during the probe wait, logging `scheduler_stopped`.

## Handoff
- task_09: MAN-001 checks the compose scheduler (`init: true`, `stop_grace_period: 30s`); the scheduler needs `DATABASE_URL` and the `SCRAPE_*` keys like `collect`. Exit codes: 0 on stop, 1 when the database is unreachable for 60+ s, 2 on invalid configuration.
