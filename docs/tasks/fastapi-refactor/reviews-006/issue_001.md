---
provider: manual
pr:
round: 6
round_created_at: 2026-10-30T22:37:00Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 543
severity: low
author: claude-code
provider_ref:
---

# Issue 001: before_commit hook targets uow.commit(), absent from UnitOfWork

## Review Comment

**Problem.** The round-5 fix for `reviews-005/issue_001` anchors the `before_commit` hook to an explicit `await uow.commit()`:

- `_spec.md` line 543 (Core Interfaces, `CollectionService.complete_run`): "calls before_commit() synchronously right before `await uow.commit()`".
- `_spec.md` line 250 (data flow step 1) and `adrs/adr-002.md` line 43 say the same thing.

But the `UnitOfWork` Protocol in the same Core Interfaces block (`_spec.md` lines 487-492) has no `commit()` method. It commits implicitly: `async def __aexit__(...)  # commit on success, rollback on error`. `_spec.md` line 843 and `_tests.md` line 16 require an in-memory `UnitOfWork` fake in `tests/fakes.py`, and that fake is written against this Protocol.

**Failure mode (reproduced).** A scratch probe (Python 3.11.5, in the session scratchpad) builds a fake UoW with only `__aenter__` and `__aexit__`, as the Protocol specifies, and a `complete_run` that follows line 543 literally. The run fails with `AttributeError: 'FakeUoW' object has no attribute 'commit' | committed: False`. Every service test that runs `complete_run` over the fake UoW (UT-059, UT-066 and the other `complete_run` cases) would fail the same way. The implementer has to pick one of two changes the spec does not state:
- add `commit()` to the Protocol, the SQLAlchemy UoW and the fake, and decide what `__aexit__` then does on success (commit again, or nothing);
- call the hook as the last statement of the `async with` body, so `__aexit__` commits.

Both are workable, but they produce different seams for the fake. The spec now describes the same transaction boundary in two incompatible ways.

**Related test gap.** The hook's ordering is only exercised through a *fake* `CollectionService` (UT-117, `_tests.md` lines 303-307). No service-level case checks that the real `CollectionService.complete_run` calls `before_commit` exactly once, after `runs.finish` and before the UoW commits, or that it is not called when `finish` raises `RunTakenOverError`. A real service that ignores the hook passes every listed test. The CLI's `cancellable` window then never closes before the commit, and only the re-read fallback keeps the outcome correct.

**Suggested fix (spec-only).**
- Make the two statements agree. Either add `async def commit(self) -> None` to `UnitOfWork`, saying that `__aexit__` then only rolls back on error, or reword lines 250 and 543 and ADR-002 to say "as the last step inside the UoW block, right before `__aexit__` commits".
- Extend UT-059/UT-066, or add a case, over the fake UoW. A recording `before_commit` is called once, after `finish` and before the fake UoW records its commit. It is not called when `finish` raises `RunTakenOverError`.

## Triage

- Decision: `VALID`
- Notes: Root cause: the round-5 wording anchored the hook to an explicit `uow.commit()` that the UnitOfWork Protocol does not have (it commits in `__aexit__`).
- Fix applied (spec-only round, no code exists): kept the Protocol unchanged. _spec.md data flow step 1, the CollectionService.complete_run comment and ADR-002 now say the hook is the last statement inside `async with uow:`, after runs.finish, and is not called when finish raises. The 'never cancelled' claim is softened: a cancel queued before the hook can still land during the commit, which the status re-read covers (the reviewer's wording note). New UT-068 checks the real service's ordering over the fake UoW, the RunTakenOverError case and the no-hook case; the matrix row is updated.
- Verified: (round 7, 2026-10-30) `_spec.md` line 250 (data flow step 1), lines 543-545 (`complete_run` comment) and `adrs/adr-002.md` line 43 now all say the hook is the last statement inside `async with uow:`, after `runs.finish`, with `__aexit__` committing; no artifact still references `uow.commit()`. The `UnitOfWork` Protocol (lines 487-492) is unchanged, so the spec states one transaction boundary. The cancel wording is softened consistently in both places, and UT-117's 'after commit' and 'cancellation landing after commit' cases still match it. UT-068 (`_tests.md` lines 267-270) covers the ordering (upserts, finish, before_commit once, commit), the no-hook-on-RunTakenOverError plus rollback case, and the `None` case. The 'Application services' matrix row now covers UT-050-UT-068, and UT-068 has no duplicate ID. A scratch probe (Python 3, Protocol-shaped fake UoW with only `__aenter__`/`__aexit__`) gave `['upsert:a','upsert:b','finish','before_commit','commit']`, `['upsert:a','upsert:b','rollback','raised RunTakenOverError']` and `['upsert:a','upsert:b','finish','commit']`, matching all three UT-068 cases.
