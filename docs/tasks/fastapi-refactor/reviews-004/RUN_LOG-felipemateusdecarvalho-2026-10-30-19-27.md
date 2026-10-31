# RUN_LOG: cy-review-round, fastapi-refactor, review round 4

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 19:27 (local)
- **Skills:** `cy-review-round` and `cy-final-verify`. This is a spec-only review: no code exists yet.
- **Scope:**
  - Verify the 3 `valid` issues: `reviews-001/issue_003`, `reviews-001/issue_010` and `reviews-003/issue_001`.
  - Find new problems that their fixes introduced.

## Questions asked and answers given

| Question | User's answer |
| --- | --- |
| None. The review ran from the caller's instructions, and no question was put to the user. | — |

## Constraints followed

- No spec artifact was edited. The only changes are the triage sections and status lines of the 3 verified issues, and the new files in `reviews-004/`.
- vagas.com and infojobs.com.br were not accessed. No Docker command was run. The v1 password is not quoted.
- The runtime checks ran in a scratch Python 3.13.4 venv: Scrapy 2.19.0, Twisted 26.10.0, pytest-socket 0.8.1, APScheduler 3.11.3, SQLAlchemy and asyncpg. Every request went to 127.0.0.1, apart from one connect-timeout probe to an unroutable private address. The venv was removed afterwards.

## Outcome

- **Verified and resolved:**
  - `reviews-001/issue_003`
  - `reviews-001/issue_010`
  - `reviews-003/issue_001`
- **New issues:**
  - `reviews-004/issue_001`, medium: a signal cancel that lands after a phase's commit orphans the run or misreports it.
  - `reviews-004/issue_002`, low: a stop during the startup run always waits the full 25 s, because of the `Popen` waitpid lock.
  - `reviews-004/issue_003`, low: UT-116 expects a class name that the recorded error never contains.
- **Clean:** no. 3 issues are `pending`.
