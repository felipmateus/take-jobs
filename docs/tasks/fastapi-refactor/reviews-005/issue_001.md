---
provider: manual
pr:
round: 5
round_created_at: 2026-10-30T22:33:23Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 250
severity: medium
author: claude-code
provider_ref:
---

# Issue 001: Round-4 signal fix relies on two interfaces the spec never defines

## Review Comment

**Problem.** The round-4 fix for `reviews-004/issue_001` is sound as behavior, but it depends on two cross-layer interactions that Core Interfaces, `CliDeps` and the UT-117 setup do not define. An implementer has to invent both, and UT-117 cannot be written as specified without them.

**1. Who clears `cancellable`, and how.** `_spec.md` line 250: "`complete_run` clears `cancellable` immediately before its `COMMIT`". ADR-002 Failure paths repeats "only before `complete_run`'s commit". But:
- `cancellable` lives on the CLI's "phase-scoped reference" (line 247), which is CLI-internal;
- `CollectionService.complete_run(run_id, report)` (line 539) takes no hook, and `CollectionService.__init__` (lines 535-536) takes only `uow_factory, relevance, clock, run_timeout`;
- the `COMMIT` happens in `UnitOfWork.__aexit__` (line 490, "commit on success"), which has no pre-commit callback either;
- `take_jobs.application` must not import `take_jobs.cli` (Architectural Boundaries, line 313), so the service cannot reach the flag directly.

The only place the CLI could intercept the moment before `COMMIT` is the UoW it builds inside `open_collection_service`, e.g. a wrapping UoW whose `__aexit__` calls a `before_commit` callback. None of this is specified, and `CliDeps.open_collection_service` is `Callable[[], AbstractAsyncContextManager[CollectionService]]` (line 598), so there is no way to pass the phase reference in. UT-117's "After commit" case (`_tests.md` line 305) says "the fake `complete_run` marks run 1 `success`, clears `cancellable`" — the fake has no defined API to do that.

**2. How the CLI re-reads the run.** Line 258: "the CLI re-reads the run (`CollectionRunQueryService.get`, in a fresh engine)". But `CliDeps` (lines 592-603) exposes only `open_collection_service`, which yields a `CollectionService`; `CollectionService` has no run getter, and nothing in `CliDeps` yields a `CollectionRunQueryService` or a runs repository. CLI unit tests use "an `open_collection_service` that yields a service over in-memory fakes" (`_tests.md` line 270). UT-117's cases "the re-read shows the run `running`" (line 303) and "the re-read shows `success`" (line 306) therefore have no seam to control: a CLI that builds a real `CollectionRunQueryService` from `settings` would hit a real database in a unit test.

**Failure mode.** Two implementers following the spec produce incompatible seams; a natural shortcut (setting `cancellable = False` in the CLI after `asyncio.run` returns, or skipping `cancellable` entirely) reintroduces exactly the post-commit cancel that `reviews-004/issue_001` fixed, and UT-117 cannot pin either behavior until a seam exists.

**Suggested fix.** Specify both seams in Core Interfaces and reference them from data flow step 1 and UT-117. For example:
- `CollectionService.complete_run(run_id, report, *, before_commit: Callable[[], None] | None = None)`, called by the service right before the UoW commits (or a `before_commit` hook on `UnitOfWork`), with the CLI passing `lambda: phase.clear_cancellable()`; the fake service in UT-117 calls that hook.
- Add `CollectionService.get_run(run_id) -> CollectionRun | None` (one UoW, `uow.runs.get`), and have the re-read use `open_collection_service()`; or add a `CliDeps` field for the re-read. Update line 258 accordingly so UT-117's fakes control the re-read result.

## Triage

- Decision: `VALID`
- Notes: Root cause: the round-4 fix named a cross-layer interaction (clearing the CLI's `cancellable` before COMMIT) and a re-read (CollectionRunQueryService) without a seam reachable from the application layer or from CliDeps.
- Fix applied (spec-only round, no code exists): _spec.md Core Interfaces: `CollectionService.complete_run(run_id, report, *, before_commit=None)` calls the hook synchronously right before `await uow.commit()`; new `CollectionService.get_run(run_id)`. Data flow step 1: the CLI passes `before_commit=phase.clear_cancellable`, and the re-read uses `get_run` through a fresh `open_collection_service()`. ADR-002 updated. UT-117: the after-commit case uses the hook, and the re-read cases are controlled through the fake `get_run`.
- Verified (round 6): both seams now exist. `_spec.md` Core Interfaces lines 541-546 define `complete_run(run_id, report, *, before_commit=None)` (hook called synchronously before the commit) and `get_run(run_id) -> CollectionRun | None`; data flow step 1 (lines 250, 259) has the CLI pass `before_commit=phase.clear_cancellable` and re-read through `get_run` on a fresh `open_collection_service()`, which `CliDeps` already exposes; ADR-002 line 43 matches; UT-117 (`_tests.md` lines 303, 305, 307) drives the hook and the re-read through the fake service and asserts a non-`None` `before_commit`. The new `await uow.commit()` wording is not on the `UnitOfWork` Protocol; tracked separately as `reviews-006/issue_001`.
