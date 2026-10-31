---
provider: manual
pr:
round: 4
round_created_at: 2026-10-30T22:26:40Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 249
severity: medium
author: claude-code
provider_ref:
---

# Issue 001: Signal cancel after a phase's commit orphans or misreports the run

## Review Comment

**Problem.** The round-3 fix for `reviews-001/issue_003` changed the collector's dispatch. A signal during **any** `asyncio.run` phase now calls `loop.call_soon_threadsafe(main_task.cancel)` (`_spec.md` data flow step 1, line 249; ADR-002 "During ingestion"). Before round 3, only ingestion was cancelled. The rule now also reaches phases that commit, and no artifact says what happens when the cancellation lands **after** the commit. That can happen at two points:
- while the `COMMIT` round trip is in flight, which commits on the server even though the client is cancelled;
- during `engine.dispose()` in `open_collection_service`'s `__aexit__`, which Safety Invariant 5 requires after every phase.

**1. `start_run` (step 2) can leave an orphaned `running` run.** Rule 24 and the failure-path table only cover a signal "after step 2", so a signal during `start_run` is unspecified. Once `start_run` has committed and is then cancelled, `asyncio.run` raises `CancelledError` and the CLI never receives `run_id`. It cannot call `fail_run(run_id, …)`, so the row stays `running`, and the next `collect` within `SCRAPE_RUN_TIMEOUT_MINUTES` (60) exits `3`.

This is the failure mode of `reviews-001/issue_003` again, and it happens on the US-004.EC-2 path. The evaluator stops `docker compose up` just as the startup collection begins: the collector reaches `start_run` about 1–2 s after launch, and the scheduler forwards SIGTERM. It contradicts:
- Safety Invariant 8 ("never stays `running`");
- rule 24 ("Only SIGKILL (or a host crash) can still leave a run `running`");
- US-004.EC-2 ("the next `docker compose up` … is not blocked by the stopped run").

Runtime evidence, Python 3.13.4 (scratch script `cancel_after_commit.py`). The script uses exactly the prescribed handler: `signal.signal` plus `call_soon_threadsafe(task.cancel)` through a phase-scoped reference. `start_run` "commits" and returns `1` inside `async with open_collection_service()`, and SIGTERM lands during the 0.3 s dispose. Output:

```
start_run phase raised CancelledError
stop_requested: True | run_id known to CLI: None | DB: {1: 'running'}
```

**2. `complete_run`, and a crash or ingest-failure `fail_run`, can be misreported.** If the cancellation lands after `complete_run`'s commit:
- the run is already `success` or `partial`, but the CLI only sees `CancelledError`;
- it then calls `fail_run(run_id, "interrupted by signal")`, and its conditional `UPDATE` affects 0 rows, so it raises `RunTakenOverError` (Safety Invariant 2);
- the CLI then prints "taken over by another process" and exits `1`.

The spec's own rule says something else: "a signal that arrives after `complete_run` committed does not change the finished run. The CLI logs `signal_after_finish` and exits with the run's normal code" (line 256). The CLI has no way to tell that the commit happened. The same applies to a `fail_run` for a crash or ingest failure, which is also a cancellable `asyncio.run` phase: only the `interrupted by signal` recording ignores signals.

**3. `interrupt()` before the crawl child exists.** `JobScraper.interrupt()` "Sends SIGTERM, joins for 5 s, then SIGKILLs" (line 577). If the phase reference already says "crawl" while `scrape()` has not yet started the spawn child, `interrupt()` has nothing to signal. `scrape()` then starts the child and crawls for up to 50 minutes, because the flag is only checked after the phase. The scheduler's 25 s wait expires, it SIGKILLs the collector, and the run stays `running`. UT-107 only interrupts after 1 s.

None of UT-117's cases (between phases; inside `complete_run` before it returns) and none of IT-013 (a)–(c) exercise these boundaries.

**Suggested fix.**
- **Do not cancel `start_run`.** During step 2, the handler only sets the flag; the step is bounded by the 5 s connect timeout. After step 2 returns `run_id`, the flag check records `interrupted by signal` and exits `4`. If step 2 refused (exit `3`) or failed to connect, the documented code applies.
- **Make post-commit work non-cancellable.** Let the handler cancel only while a phase is in its cancellable section, and clear that state immediately before `commit`, for example with a `cancellable` flag on the phase reference, or by wrapping commit plus dispose in `asyncio.shield`. Do not cancel crash or ingest-failure `fail_run` either.
- **If a cancelled phase may still have committed**, have the CLI read the run's status before reporting:
  - if the run is already finished, it is the "late signal" case: log `signal_after_finish` and exit with that run's code;
  - in no case print the "taken over" message.
- **Specify `interrupt()` before start.** It records the request, and `scrape()` checks it right after `process.start()`, terminating the child if it is set. Alternatively, the CLI sets the crawl phase reference only after the child is started.
- **Add UT-117 cases:**
  - the handler fires inside a fake `start_run` after it "committed" → `fail_run(run_id, "interrupted by signal")`, exit `4`;
  - the handler fires after a fake `complete_run` "committed" → no "taken over" message, exit with the run's code;
  - `interrupt()` before the child starts → `ScrapeInterruptedError` within 7 s.
- Extend rule 24's scope from "after `start_run`" to "from `start_run` on".

## Triage

- Decision: `VALID`
- Notes: Root cause: round 3 made every asyncio.run phase cancellable, including start_run and the post-commit part of complete_run, and interrupt() had no defined behavior before the child exists.
- Fix applied (spec-only round, no code exists): _spec.md data flow step 1: start_run and every fail_run are never cancelled (flag only); complete_run is cancellable only while `cancellable` is set, which it clears right before COMMIT; after any CancelledError the CLI re-reads the run (finished → signal_after_finish and the run's exit code; running → interrupted by signal, exit 4); 'taken over' is printed only for RunTakenOverError from complete_run itself. Rule 24 now covers signals 'from start_run on'. interrupt() records the request, and scrape() checks it before and right after process.start(). ADR-002 updated. Tests: UT-117 adds the start_run, after-commit and cancel-after-commit cases; UT-107 adds interrupt-before-start.
- Verified: (review round 5) `_spec.md` data flow step 1 (lines 246-261) now makes `start_run` and every `fail_run` flag-only, makes `complete_run` cancellable only while `cancellable` is set and cleared before `COMMIT`, and re-reads the run after any `CancelledError` (finished -> `signal_after_finish` + run's code; running -> `interrupted by signal`, exit 4; 'taken over' only from `complete_run`'s own `RunTakenOverError`). Rule 24 (line 117) covers signals from `start_run` on. `JobScraper.interrupt` docstring (lines 496-499) and the `ScrapyJobScraper` comment (lines 584-587) define interrupt-before-start. ADR-002 Failure paths match. UT-117 gains the `start_run`, after-commit and cancel-after-commit cases; UT-107 gains interrupt-before-start. The three failure modes in this issue are closed. The interfaces the fix relies on (how `complete_run` clears the CLI's `cancellable` flag, and how the CLI re-reads the run through `CliDeps`) are not defined; that is a new gap tracked as `reviews-005/issue_001`, and the flag-only terminal `fail_run` interaction is tracked as `reviews-005/issue_002`.
