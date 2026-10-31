# RUN_LOG — cy-fix-reviews — fastapi-refactor, review round 2

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 18:06
- **Skill:** `cy-fix-reviews` (spec-only; no code exists yet)
- **Scope:** 9 issues
  - reopened from round 1: `reviews-001/issue_003, 004, 010, 014, 016`
  - new in round 2: `reviews-002/issue_001`–`004`

## Questions asked and answers given

| Question | User's answer |
| --- | --- |
| Earlier: Shall I run reviewer round 2 to confirm the fixes? | "Sim, rode a rodada 2 do reviewer para verificar as correções antes de gerar as tasks." |
| Shall I apply the proposed fixes for the 9 issues? (The proposal table listed one fix per issue.) | "Sim, aplique as correções propostas para os 9 issues da rodada 2 com cy-fix-reviews." |

No further questions were asked during the skill run.

## Fixes applied (as proposed and approved)

- **R2-001 (high), pipe deadlock:** the parent reads the report before `join()`, closes the child's end of the pipe, and uses `connection.wait`. New test UT-109, with a report over 1 MiB; UT-108 now has a time bound.
- **R1-003 (high), signals:**
  - The collector is the only signal handler. The child ignores SIGINT and runs without Scrapy handlers.
  - During the crawl: SIGTERM to the child, a 5-second wait, then SIGKILL. During ingestion: the task is cancelled and the transaction rolled back.
  - Invariant 6 now uses `Popen`. IT-013 is parametrized for crawl, Ctrl+C and ingestion.
  - Two refinements on the approved fix, needed to meet the reviewer's evidence: the child ignores SIGINT, and `install_signal_handlers=False`.
- **R1-004:** US-019.EC-3, MAN-001 and ADR-004 (Context and risk) are aligned with the 24-hour rule.
- **R1-010:**
  - URL resolution against the page URL, plus `allowed_domains` and an off-origin guard (UT-039).
  - `child_initializer` network guard in the crawl child (UT-116).
  - UT-115 now expects `SocketConnectBlockedError`.
- **R1-014:** the secret scan excludes `docs/**/*.md` and its own module and fixtures, with self-check cases.
- **R1-016:** `to_standard_crontab` expands day-of-week into an explicit Sunday-first list of names. UT-019 covers `0-4`, `0-6`, `5-7`, `*/2` and `sun-thu`.
- **R2-002:** O5 uses the 7 complete days ending yesterday. IT-014 has cases (a) 71.4 and (b) 100.0.
- **R2-003:** the healthcheck uses `$$POSTGRES_USER`/`$$POSTGRES_DB`. UT-110 asserts it.
- **R2-004:** new seams `CliDeps.relevance`/`clock`/`sleep`/`scheduler_factory` and `take_jobs.cli.scheduler`. `get_settings` reads `app.state.settings`. The CLI test preamble and UT-077, UT-085 and UT-087 are fixed.

**Files changed:** `_spec.md`, `_user_stories.md`, `_tests.md`, `adrs/adr-002.md`, `adrs/adr-004.md`, and the triage sections of the 9 issue files (`status: valid`). Nothing is marked `resolved`; the reviewer does that.

## Verification

- `check-spec-markers.py` with markers 4, 5 and 6 required → OK (5/5).
- Every test ID cited in the spec, ADRs and stories is defined in `_tests.md`. The new IDs UT-039, UT-109 and UT-116 are in the coverage matrix.
- Stale-text sweep: no scheduler `subprocess.run`, no unescaped `$POSTGRES_USER`, no `mon-fri` expectation, no `SocketBlockedError`, and no `today − 6` window left.
- `cy-final-verify` product checks (lint, tests) do not apply: no code exists yet.
- Nothing was committed.
