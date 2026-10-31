# task_01 memory

## Outcome
Completed. v2 skeleton, `Settings`, import-linter contracts, pytest guard and `uv.lock` in place; v1 deletion stays staged.

## Decisions
- Packages `domain`, `application`, `infrastructure/{db,scraping}`, `api`, `cli` are empty `__init__.py`; `cli/main.py::main` handles only `-h/--help` (exit 0) and exits 2 otherwise until task_06.
- `.gitignore`: removed `../env/`, `./src/env/`, `../.DS_Store`; added `.ruff_cache/` (`.env`, `.venv`, `.coverage*`, `htmlcov/` already existed).
- Extra tests beyond UT-020-027/UT-115: other invalid keys (API_PORT, LOG_LEVEL, JOB_INACTIVE_AFTER_DAYS, SCRAPE_ON_START) and `.env` empty-value pass-through.
- Verified the contracts break on deliberate violations (temporary files, removed).

## Evidence
`uv run ruff format --check`, `ruff check`, `lint-imports` (8 kept), `pytest` (17 passed), `uv lock --check`, `python -m take_jobs --help` all exit 0.
