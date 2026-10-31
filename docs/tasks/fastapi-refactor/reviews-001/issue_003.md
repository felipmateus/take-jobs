---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_user_stories.md
line: 105
severity: high
author: claude-code
provider_ref:
---

# Issue 003: Stopped collections block restarts for 2h or are saved as success

## Review Comment

**Problem.** No artifact defines what happens when a collection is stopped (SIGTERM or SIGINT). Two concrete failure modes follow.

**1. An orphaned run blocks the evaluator's restart (hurts O4 and US-004).**
- The evaluator runs `docker compose up` in the foreground. The startup run begins, and the evaluator stops the stack (Ctrl+C or `docker compose down`).
- Compose sends SIGTERM to the scheduler's PID 1. A Python PID 1 with no SIGTERM handler ignores it, so Docker SIGKILLs the container after 10 s, together with the `collect` child (`subprocess.run`, ADR-004).
- The run row stays `running`, and nothing was ingested, because ingest happens only after the crawl (ADR-002).
- On the next `docker compose up` the store is still empty. The startup collect hits rule 13, because the orphan is younger than `SCRAPE_RUN_TIMEOUT_MINUTES` (120), and exits `3`.
- Result: no data until the next 06:00, or until a manual `collect` two hours later.

US-004.EC-2 (line 105) calls this intended ("restart while the startup run is still in progress → no second run starts"). Under Compose, though, the run cannot still be in progress: it dies with its container.

**2. A gracefully stopped crawl is recorded as success.** `CrawlerProcess` installs SIGINT/SIGTERM handlers. The first signal triggers a graceful shutdown (close reason `shutdown`), and `process.start()` then **returns normally**. Under the spec's data flow (lines 219–220), `complete_run` then records every truncated combination as `success`, with partial pages. This happens with `docker compose run --rm scheduler take-jobs collect` followed by Ctrl+C. Run history and O5 then report success for an aborted run.

**Suggested fix.**
- Specify signal handling:
  - the scheduler installs a SIGTERM handler (or Compose uses `init: true`) and forwards the signal to the child;
  - `collect` treats a non-`finished` spider close reason, or a received signal, as a run-level failure, calling `fail_run(run_id, "interrupted by signal")` and exiting `1`;
  - define the exit code for a run stopped by a signal.
- Re-word US-004.EC-2 to match.
- Add tests:
  - a UT: the scraper maps spider close reason `shutdown` to an error;
  - an IT: a SIGTERM sent to `collect` during the crawl leaves the run `failed`, not `running` or `success`.

## Triage

- Decision: `VALID`
- Notes: Root cause: no signal handling; Scrapy graceful shutdown returned normally; the scheduler as PID 1 ignored SIGTERM.
- Fix applied (spec-only round, no code exists): _spec.md rule 24, Safety Invariant 8, Compose contract (init: true, stop_grace_period 30s); ADR-004 signal forwarding; ADR-002 close-reason mapping; _dx.md exit 4; US-003.EC-5, US-004.EC-2 reworded; UT-087, UT-104, UT-107, IT-013.
- Reopened (round 2, 2026-10-30): the scheduler-side fix is in place, but the signal chain through the new spawned crawl child still lets both original failure modes happen. Runtime evidence: Scrapy 2.19.0, Python 3.13, a spawn child running `CrawlerProcess` with `TWISTED_REACTOR=None` and `DOWNLOAD_TIMEOUT=30`, against a local 127.0.0.1 server that holds one listing response for 25 s:
  - One SIGTERM to the child (the scheduler/`docker compose down` path): `Closing spider (shutdown)`, then the child exits **19.7 s** later, because Scrapy's graceful close waits for in-flight downloads. The bound is `DOWNLOAD_TIMEOUT` (30 s) plus the parent's own `fail_run` (new engine). That exceeds the scheduler's 25 s wait inside `stop_grace_period: 30s` (Safety Invariant 8). Docker then SIGKILLs the container, the run stays `running`, and the next `docker compose up` gets exit `3` for up to 60 minutes. That is failure mode 1 of this issue, contradicting US-004.EC-2.
  - Ctrl+C on `docker compose run --rm scheduler take-jobs collect` (or `uv run take-jobs collect`): the tty sends SIGINT to the whole foreground process group, so the crawl child receives SIGINT directly, and then rule 24's forwarded SIGTERM. Observed: `Received SIGTERM twice, forcing unclean shutdown`; `spider_closed` never fires; close reason `None`. ADR-002 and `_spec.md` map only `finished`, `closespider_timeout` and `shutdown`, so the outcome is undefined. Treated as finished, it is recorded `success`/`partial` with truncated terms (failure mode 2). If the child dies without a report, it is exit `1` with a crash message instead of exit `4` (US-003.EC-5).
  - Safety Invariant 6 still prescribes `subprocess.run([...], shell=False)` for the scheduler. `subprocess.run` exposes no child handle to forward SIGTERM to, which contradicts ADR-004 Launch (`subprocess.Popen`, kept so a signal can be forwarded) and UT-084.
  - Rule 24 says signals are handled at any phase after `start_run`, but IT-013 only signals during the crawl. No test pins SIGTERM during ingest (`asyncio.run(complete_run)`), where a flag-only handler would let the run finish `success`.
  Still needed:
  - The crawl child ignores SIGINT/SIGTERM from the tty (for example `signal.signal(SIGINT, SIG_IGN)` at child start); the collector parent is the only signal source.
  - The parent maps "a signal was received" to `ScrapeInterruptedError` whatever the child reports.
  - The parent waits at most N s for the child after forwarding, then kills it, with N plus `fail_run` well under 25 s.
  - Change Invariant 6 to `Popen`.
  - Extend IT-013 with three variants: SIGINT to the helper's process group; a fixture response delayed beyond N; SIGTERM during a slow ingest.
- Round-2 fix: rule 24 rewritten so the collector is the only signal handler. The crawl child sets SIGINT to SIG_IGN and runs CrawlerProcess.start(install_signal_handlers=False), so SIGTERM terminates it at once. scraper.interrupt() sends SIGTERM, waits 5 s, then SIGKILLs; ingestion is cancelled via loop.add_signal_handler, which rolls back the transaction. The parent decides the interruption whatever the child reports. Close reason None/shutdown is mapped to 'crawl closed: <reason>'. Safety Invariant 6 now uses Popen; Invariants 5 and 8 updated; ADR-002 updated. Tests: UT-107 rewritten (interrupt within 7 s), IT-013 parametrized (a) SIGTERM during crawl, (b) SIGINT to the process group, (c) SIGTERM during ingestion, with exit 4 within 12 s.
- Reopened (round 3, 2026-10-30): the child side is now sound. In Scrapy 2.19.0, `CrawlerProcess.start(install_signal_handlers=False)` calls `reactor.run(installSignalHandlers=False)` and skips `install_shutdown_handlers`, so SIGTERM kills the child at once. Two parent-side gaps still let this issue's failure mode 1 (orphaned `running` run, exit `3` on the next start) and an orphaned crawler happen:
  1. **The prescribed handler mechanism removes its own handlers.** Data flow step 1 installs the collector's handlers once with `signal.signal`, then has every `asyncio.run` phase use `loop.add_signal_handler`. When that loop closes, asyncio's `remove_signal_handler` resets the signal to `SIG_DFL` (SIGTERM) or `default_int_handler` (SIGINT); it does not restore the previous handler. Runtime, Python 3.13.4 (scratch script `sig_restore.py`): before phase 2 both handlers are the collector's function; after `asyncio.run(start_run())` they are `0` (SIG_DFL) and `default_int_handler`; a SIGTERM during the following "crawl" kills the process with exit 143. So, as specified:
     - SIGTERM during the crawl kills the collector, the run stays `running`, and the crawl child keeps crawling the real sites (it is not signalled).
     - Ctrl+C during the crawl raises `KeyboardInterrupt` in the parent, while the child ignores SIGINT and keeps crawling. multiprocessing's exit hook then joins the non-daemon child, for up to 50 min.
     - A signal between phases (after `scrape()` returns and before the ingest loop exists) reaches a handler that only calls `scraper.interrupt()` on a finished child, so the run can end `success`. That violates rule 24 ("at any step after 2").
     IT-013 (a)/(b) would fail, but the spec prescribes the broken mechanism, so the implementer has to redesign it.
     Fix: one process-wide `signal.signal` handler for the whole command that records a "stop requested" flag and then dispatches by phase. During the crawl it calls `scraper.interrupt()`. During an `asyncio.run` phase it uses `loop.call_soon_threadsafe(main_task.cancel)`, through a phase-scoped reference. Do not use `loop.add_signal_handler`; if it is used, re-install the handlers after every `asyncio.run`. After each phase, the CLI checks the flag, so a signal between phases also gives `interrupted by signal`, exit 4. Add an IT-013 variant, or a UT, that sends the signal right after `scrape()` returns.
  2. **SIGTERM during the startup run is never forwarded.** `run_scheduler` is specified as `wait_for_database → run_startup → configure_scheduler → install make_shutdown_handler → scheduler.start()`, and `run_startup` calls the runner, which waits for the child (UT-084 "waits for it"; UT-080 "before the scheduler loop starts"). For the whole startup collection (about 9 min on the Golden Path), the scheduler process has Python's default SIGTERM action. Runtime (scratch script `sched_order.py`): SIGTERM to a scheduler in `run_startup` → the scheduler exits with -15, and its collector child never receives SIGTERM. In the container, tini (`init: true`) then exits, and the kernel SIGKILLs the rest of the PID namespace, so the run stays `running`. This is exactly US-004.EC-2: the evaluator stops `docker compose up` during the first startup run, and the next `up` within 60 min gets exit 3 and no data until the next 06:00. `_dx.md` › CLI also promises "Stopping a collection (Ctrl+C, `docker compose stop`) is safe". UT-087 tests the handler in isolation, and no test pins when it is installed. The same order also contradicts the `_dx.md` Golden Path log, which shows `scheduler_started` before `startup_collection`.
     Fix: install the shutdown handler before `wait_for_database`/`run_startup`, so it forwards to whichever collector is running. Or run the startup collection as a one-off job after `scheduler.start()`. Add a UT: `run_scheduler` with a runner that blocks, plus a SIGTERM (or a direct handler call) during `run_startup` → `terminate()` is called on the startup child.
  Minor, same area: rule 24's "fail_run with a 5-second connect timeout" has no owner. `DATABASE_URL` and the engine contract set no connect timeout (asyncpg's default is 60 s), so state where it is configured.
- Round-3 fix: one process-wide signal.signal handler for the whole collect command (never loop.add_signal_handler), with a stop_requested flag and phase-scoped dispatch (crawl → scraper.interrupt(); asyncio phase → loop.call_soon_threadsafe(main_task.cancel)). The flag is checked after every phase, so a signal between phases gives exit 4; late signals after commit are logged and do not change the run. Scheduler order fixed: the shutdown handler is installed first, then wait_for_database → configure_scheduler (log scheduler_started) → run_startup → start(). The fail_run connect-timeout owner is defined (make_engine connect_args timeout=5). Files: _spec.md data flow step 1, scheduler start-up, rule 24, Safety Invariant 8, Core Interfaces (run_scheduler, make_shutdown_handler); ADR-002, ADR-004. Tests: UT-117 (handler persists across asyncio.run; signal between phases and during ingest), UT-088 (handler installed before the startup run, forwards to the startup collector), UT-087 updated.
- Verified (round 4, 2026-10-30): both round-3 gaps are closed. Data flow step 1, rule 24, Safety Invariant 8 and ADR-002 prescribe one process-wide `signal.signal` handler with a `stop_requested` flag checked after every phase and phase-scoped dispatch; no artifact prescribes `loop.add_signal_handler` any more (grep). Runtime, Python 3.13.4: a `signal.signal` handler for SIGTERM/SIGINT is still installed after two `asyncio.run` calls, and `asyncio.run` does not replace a non-default SIGINT handler (scratch `persist.py`); `loop.call_soon_threadsafe(task.cancel)` from that handler cancels the running phase (scratch `cancel_after_commit.py`). Scheduler start-up and `run_scheduler` install `make_shutdown_handler` before `wait_for_database` and `run_startup`, and UT-088 pins that order and the forwarding to the startup collector. The `fail_run` connect-timeout owner is defined: `create_async_engine(..., connect_args={"timeout": 5})` with asyncpg raises `TimeoutError` after 5.0 s against an unroutable address (scratch `connect_timeout.py`). New problems introduced by this fix are tracked separately in `reviews-004/issue_001.md` (cancellation landing after a phase's commit) and `reviews-004/issue_002.md` (the 25 s wait inside the startup run).
