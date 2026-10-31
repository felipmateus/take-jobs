# RUN_LOG: cy-review-round, take-jobs v2 spec, round 3

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 19:15 (America/Sao_Paulo)
- **Skills:** `cy-review-round`, with `cy-final-verify` for the closing checks
- **Slug:** `fastapi-refactor`
- **Scope:** spec artifacts only (no implementation exists): `_prd.md`, `_spec.md`, `_user_stories.md`, `_dx.md`, `_tests.md` and `adrs/`. Also the 9 `valid` issues: round 1 issues 003, 004, 010, 014 and 016, and round 2 issues 001 to 004.
- **Output:**
  - status updates in `reviews-001/` (issues 003, 004, 010, 014 and 016) and in `reviews-002/` (issues 001 to 004);
  - one new issue, `reviews-003/issue_001.md`.

## Request (relayed by the launching agent)

This round has two jobs:
- Verify the 9 `valid` issues, and mark each one `resolved` or reopen it with evidence.
- Find new problems introduced by the round-2 fixes.

Constraints for the run:
- Do not edit spec artifacts.
- Do not access vagas.com or infojobs.com.br, and never quote the v1 password.
- Do not run `docker` commands or touch Docker Desktop. Python-only checks in a scratch venv are allowed.

## Questions asked during this run

None. I asked the user no questions, and the user gave no answers during this run.

## Verdicts on earlier issues

- **Resolved (7):** round 1 issues 004, 014 and 016; round 2 issues 001, 002, 003 and 004.
- **Reopened to `pending` (2):**
  - Round 1 issue 003. Two gaps:
    - The specified `loop.add_signal_handler` use resets the collector's handlers when each `asyncio.run` loop closes.
    - `run_scheduler` installs the shutdown handler only after the synchronous startup run.
  - Round 1 issue 010. The pytest-socket guard in the crawl child does not cover Twisted's `connect_ex`, so UT-116 is hollow.

## New issues

- 001 (low): the probe used by `startup_reason`, `wait_for_database`, UT-067 and UT-085 has no contract, and `CollectionRunner` is undefined.

## Runtime checks (local only, no job-board access, no Docker)

All checks ran in a scratch venv with Python 3.13.4, Scrapy 2.19.0, Twisted 26.10.0, pytest-socket 0.8.1 and APScheduler 3.11.3.

- **pytest-socket guard in a spawn child:**
  - with the guard alone, a Scrapy request to a loopback address outside the allow-list succeeded;
  - with `connect_ex` also guarded, the same request was blocked.
- **Signal handlers:** `asyncio.run` combined with `loop.add_signal_handler` resets the handlers that `signal.signal` installed earlier.
- **Scheduler start-up:** a SIGTERM sent to a scheduler that is still in a synchronous startup run does not reach the collector.
- **Report pipe:** the specified hand-off passed a 15,000-job (1,356 KiB) report, and a crash without a report did not hang.
- **APScheduler:** every `to_standard_crontab` output in UT-019 was accepted, and the next fire times matched. A scheduler that was never started still exposes the job attributes UT-083 checks.
- **Secrets:** the IT-012 secret-scan patterns, with the round-2 exclusions, found nothing in the tree. A separate check looked for the v1 password value without printing it and found it in no working-tree file.

The scratch venv and scripts were deleted after the run.
