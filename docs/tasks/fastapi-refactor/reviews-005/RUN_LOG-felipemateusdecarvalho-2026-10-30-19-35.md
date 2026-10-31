# RUN_LOG — cy-fix-reviews — fastapi-refactor, review round 5

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 19:35
- **Skill:** `cy-fix-reviews` (spec-only; no code exists yet)
- **Scope:** `reviews-005/issue_001` (medium), `issue_002` (low)

## Questions asked and answers given

| Question | User's answer |
| --- | --- |
| Standing instruction for this flow | "seguir o fluxo de forma automatica" |
| (Mid-run status check) | "travou?" — answered: no, review round 5 was still running |

No questions were asked during this run. Both fixes follow the reviewer's suggestion, and neither needs a product decision.

## Fixes applied

- **001, missing seams:**
  - `CollectionService.complete_run(..., before_commit=None)` calls the hook right before `await uow.commit()`. The CLI passes `phase.clear_cancellable`.
  - New `CollectionService.get_run(run_id)`. The CLI's re-read after a cancelled phase uses it through a fresh `open_collection_service()`.
  - UT-117 cases now use these seams.
- **002, post-phase stop-flag check:**
  - The check applies only after the non-terminal phases (`start_run` and the crawl).
  - After a terminal phase, a set flag only logs `signal_after_finish`, and the exit code is kept. `fail_run` is never called twice.
  - The failure-path table, rule 24, Safety Invariant 8 and ADR-002 are aligned.
  - New UT-117 case: a signal during the crash `fail_run`.

**Files changed:** `_spec.md`, `_tests.md`, `adrs/adr-002.md`, and the triage sections of the 2 issue files (`status: valid`).

## Verification

- `check-spec-markers.py` with markers 4, 5 and 6 required → OK (5/5).
- No remaining "after every phase" or `CollectionRunQueryService.get` re-read wording.
- Issue counts: 25 `resolved`, 2 `valid` (this batch).
- `cy-final-verify` product checks do not apply: there is no code yet.
- Nothing was committed.
