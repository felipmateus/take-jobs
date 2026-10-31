# task_10 memory

## Outcome
Completed. New: `.github/workflows/ci.yml`, `src/take_jobs/infrastructure/db/metrics.sql`, `tests/static/{test_ci,test_readme,test_repo}.py`, `tests/integration/test_o5_query.py`. Rewritten: `README.md` (English). Local tag `v1` created with `git tag v1 52018b3` (`git rev-parse v1^{commit}` = `52018b30fc74...`); not pushed. Full gate green: ruff format/check, `lint-imports` (8 kept), `pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80`: 437 passed in 115 s, coverage 99.55%.

## Decisions
- `metrics.sql` is the `_spec.md` > Monitoring query verbatim (dedented). UT-112 asserts the README embeds it exactly and that it matches the spec text line by line, so the three cannot drift. IT-014 reads the same file and binds `:tz` and `:expected`.
- IT-014 seeds each run at local noon of day D-n, computed in SQL from `now()` in `America/Sao_Paulo`; a date change between seeding and the query (midnight in Sao Paulo) could in theory flake it. The `running` variant of (b) leaves `finished_at` null. Parameters `:n` needs `CAST(... AS integer)` because asyncpg cannot infer `date - $n`.
- UT-111 reads `on` as `True` as well (PyYAML YAML 1.1). UT-113 skips only when the tag is absent (the CI runner has it only when the tag is pushed). UT-112 also checks the CI badge and `docker compose up --build` within the first 25 lines, the config keys, that a README URL with user info only carries the development default, and that the v1 file paths are cited.
- README "v1 -> v2" cites v1 file paths only and never quotes the v1 password; it states the password is in git history and tells anyone who ran v1 to rotate it. Real MAN-001/MAN-003 numbers (15 s up, 33 s collection, 51 s to jobs, `recent_run_exists`, 48/50 = 96%) and the IT-011 latency are cited.
- The secret scan (IT-012) scans test files too: a test regex or comment containing `password:` or `://user:x@` shape trips it, so UT-112 builds the URL regex from parts.

## MAN status
- MAN-005: tag points to `52018b3`; README has Overview, Running, Querying the API, Configuration and v1 -> v2; `docs/tasks/fastapi-refactor/` holds PRD, spec, companions, tasks, `reviews-001`..`reviews-006` and `memory/`. Verified by UT-112/113/114.
- MAN-004: pending user action. The user must push the branch (and the `v1` tag if wanted) and confirm the GitHub Actions run is green and the badge renders. The workflow was not run on GitHub; its local equivalent (the same four commands) passed.
- MAN-002: post-delivery (O5 after 7 days of operation); the README's last bullet says "Not measured yet".

## Follow-ups (not done)
- Add `visual` and `materiais` to the default exclude list (from task_09 MAN-003), which `_dx.md` fixes.
