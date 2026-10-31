# RUN_LOG — cy-fix-reviews — fastapi-refactor, review round 4

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 19:30
- **Skill:** `cy-fix-reviews` (spec-only; no code exists yet)
- **Scope:** `reviews-004/issue_001` (medium), `issue_002` (low), `issue_003` (low)

## Questions asked and answers given

| Question | User's answer |
| --- | --- |
| Standing instruction for this flow | "seguir o fluxo de forma automatica" |

No questions were asked during this run. The fixes follow the reviewer's suggested direction, and none requires a product decision.

## Fixes applied

- **001, signal cancels a phase after its commit:**
  - `start_run` and every `fail_run` are never cancelled; the handler only sets the flag.
  - `complete_run` can be cancelled only before its `COMMIT`.
  - After any cancellation, the CLI re-reads the run. A finished run means a late signal: the CLI keeps the run's own exit code. A running run means `interrupted by signal`, exit `4`.
  - `interrupt()` before the crawl child exists is recorded and honored.
  - Rule 24 now covers signals "from `start_run` on".
  - Tests: UT-117 and UT-107 extended.
- **002, `Popen.wait` lock:** `SubprocessCollectionRunner` polls `poll()` in both `run()` and `terminate_current()`. Tests: UT-084 updated; new UT-089 uses a real child in the main thread.
- **003, UT-116 error format:** the generic errback format is now `<ExceptionType>: <message>`, set in `_spec.md` Integration Points and ADR-002. UT-116 is aligned.

**Files changed:** `_spec.md`, `_tests.md`, `adrs/adr-002.md`, and the triage sections of the 3 issue files (`status: valid`).

## Verification

- `check-spec-markers.py` with markers 4, 5 and 6 required → OK (5/5).
- Every test ID cited in the spec, ADRs and stories is defined in `_tests.md`.
- Issue counts: 22 `resolved`, 3 `valid` (this batch).
- `cy-final-verify` product checks do not apply: there is no code yet.
- Nothing was committed.
