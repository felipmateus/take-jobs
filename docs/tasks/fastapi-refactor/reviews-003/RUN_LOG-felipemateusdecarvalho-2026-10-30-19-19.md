# RUN_LOG — cy-fix-reviews — fastapi-refactor, review round 3

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 19:19
- **Skill:** `cy-fix-reviews` (spec-only; no code exists yet)
- **Scope:** 3 issues
  - reopened in round 3: `reviews-001/issue_003` (signals), `reviews-001/issue_010` (FR-30 guard);
  - new in round 3: `reviews-003/issue_001` (startup probe contract).

## Questions asked and answers given

| Question | User's answer |
| --- | --- |
| Earlier: Shall I run reviewer round 3 to confirm? | "seguir o fluxo de forma automatica" |

The user asked for the flow to continue automatically, so no questions were asked during this run. All three fixes are technical, follow the reviewer's suggested direction, and need no product decision.

## Fixes applied

- **R1-003, signals:**
  - **Collector:** one process-wide `signal.signal` handler for the whole `collect` command, never `loop.add_signal_handler`. A stop flag is checked after every phase, and the handler dispatches by phase.
  - **Scheduler:** it installs its shutdown handler before the probe and the startup run.
  - **Engine:** a 5-second connect timeout on CLI engines.
  - **Tests:** new UT-117 and UT-088; UT-087 updated.
- **R1-010, network guard:** `install_test_socket_guard` also wraps `socket.connect_ex`. UT-116 now uses a real Scrapy request and asserts 0 server hits, plus a control case.
- **R3-001, startup probe contract:**
  - `UnitOfWork.probe`, `CollectionService.ping()` and a defined `startup_reason()`.
  - A typed `wait_for_database`.
  - The `CollectionRunner` protocol and `SubprocessCollectionRunner.current`.
  - Tests: UT-067, UT-084, UT-085 and UT-087 updated.

**Files changed:** `_spec.md`, `_tests.md`, `adrs/adr-002.md`, `adrs/adr-004.md`, and the triage sections of the 3 issue files (`status: valid`).

## Verification

- `check-spec-markers.py` with markers 4, 5 and 6 required → OK (5/5).
- Every test ID cited in the spec, ADRs and stories is defined in `_tests.md`.
- No remaining prescription of `loop.add_signal_handler`.
- `cy-final-verify` product checks do not apply: there is no code yet.
- Nothing was committed.
