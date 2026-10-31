---
provider: manual
pr:
round: 3
round_created_at: 2026-10-30T22:15:00Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 512
severity: low
author: claude-code
provider_ref:
---

# Issue 001: Startup probe has no contract: CollectionService lacks a probe

## Review Comment

**Problem.** Several contracts use a database probe, but none of them can reach it:
- Rule 14 and the scheduler start-up both depend on the probe.
- The new scheduler seams added for round-2 issue 004 call it.
- UT-067 and UT-085 test against it.

The details:

- `CollectionService.startup_reason()` (`_spec.md` line 521) is documented as "rule 14, via JobStoreProbe + latest_finished + Clock". However, `CollectionService.__init__` (line 513) takes only `uow_factory, relevance, clock, run_timeout`, and `UnitOfWork` (line 466) exposes only `jobs` and `runs`. No path leads to `JobStoreProbe.is_empty()`.
- UT-067 (`_tests.md` line 266) builds `CollectionService` "with a fake probe". The specified constructor has no argument to pass it to.
- `wait_for_database(open_service: ..., *, sleep, max_wait_s=60)` (line 586) leaves its first argument untyped. Scheduler start-up step 1 (line 284) says it probes with "`ping`, `is_empty`, and the latest finished run". `CollectionService` has no `ping`, and `CliDeps` exposes only `open_collection_service`. UT-085 ("a probe that raises a connection error 3 times and then succeeds") therefore has no specified object to fake.
- A smaller gap in the same seams: `make_shutdown_handler(scheduler, runner)` must reach "the runner's child" (UT-087: "the runner holds a fake `Popen` child"). `CollectionRunner` is never defined, so the attribute or method that exposes the running `Popen` is left to the implementer.

These are the same class of gap as round-2 issue 004: the implementer has to invent the seam that UT-067, UT-085 and UT-087 depend on, and the tests' fakes then follow that invention.

**Suggested fix.**
- Add `probe: JobStoreProbe` to `CollectionService.__init__`, or add `probe` to `UnitOfWork`, and state which one UT-067 uses.
- Type `wait_for_database`'s first parameter. For example, `probe_factory: Callable[[], AbstractAsyncContextManager[JobStoreProbe]]` as a `CliDeps` field, or `open_collection_service` plus a `CollectionService.ping()`.
- Define `CollectionRunner` in Core Interfaces (`run(trigger) -> int`, plus a `current: subprocess.Popen | None` attribute or a `terminate_current(timeout)` method), so that UT-084 and UT-087 target one interface.

## Triage

- Decision: `VALID`
- Notes: Root cause: CollectionService and UnitOfWork exposed no probe, wait_for_database's first parameter was untyped, and CollectionRunner was never defined.
- Fix applied (spec-only round, no code exists): UnitOfWork gains `probe: JobStoreProbe`; CollectionService gains `ping()`, and `startup_reason()` is defined over uow.probe, uow.runs.latest_finished and the clock; `wait_for_database(open_service: Callable[[], AbstractAsyncContextManager[CollectionService]], ...)` pings through a fresh engine per attempt; the `CollectionRunner` protocol (`run(trigger) -> int`, `terminate_current(wait_s)`) and `SubprocessCollectionRunner.current` are defined in take_jobs/cli/runner.py. Tests: UT-067 (fake UoW probe, ping), UT-084 (run/terminate_current/idle), UT-085 (open_service.ping), UT-087 (runner.terminate_current).
- Verified (round 4, 2026-10-30): `UnitOfWork.probe: JobStoreProbe` (same session), `CollectionService.ping()` and `startup_reason()` defined over `uow.probe`, `uow.runs.latest_finished()` and the clock; `wait_for_database(open_service: Callable[[], AbstractAsyncContextManager[CollectionService]], *, sleep, max_wait_s)` is typed; `CollectionRunner` (`run(trigger) -> int`, `terminate_current(wait_s)`) and `SubprocessCollectionRunner.current` are defined in `take_jobs/cli/runner.py`, and `CliDeps.runner` uses the protocol. UT-067 fakes `uow.probe` and `uow.runs`, UT-084 targets `run`/`terminate_current`/idle, UT-085 fakes `ping()`, UT-087 asserts `runner.terminate_current(25)`; every seam the tests fake now exists in Core Interfaces. Resolved.
