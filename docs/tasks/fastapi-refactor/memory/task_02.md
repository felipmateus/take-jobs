# task_02 memory

## Outcome
Completed. `take_jobs.domain` has `models.py`, `ports.py`, `errors.py` and `rules.py`; `Settings._valid_cron` now uses `CronTrigger.from_crontab(to_standard_crontab(value))`.

## Decisions
- `final_run_status([])` returns `failed`: a run with no result is not a success (rule 12 is silent on it).
- `normalize` uses NFKD + drops combining marks + `str.isalnum`; keywords are matched as padded substrings (whole word/phrase). `RelevancePolicy` normalizes keywords, drops blank ones and raises `ValueError("include keywords must not be empty")` when none remain.
- `classify_seniority`: left-most start wins; same start, the longer keyword wins.
- `to_standard_crontab`: requires exactly 5 fields; `*` stays unchanged; `a/n` (no range) expands to `a-7`; ranges with `low > high` (e.g. `5-2`) are rejected, as in standard cron; fields are re-joined with single spaces.
- `RunAlreadyActiveError(run_id, started_at)` and `RunTakenOverError(run_id)` expose those attributes. `RunTotals.from_results` returns `Self`, because Python 3.13 has no deferred annotations.
- Extra tests beyond UT-001-019: errors/ports surface (`tests/unit/domain/test_errors_and_ports.py`), cron accepted/rejected in `tests/unit/test_config.py`.

## Evidence
ruff format/check, `lint-imports` (8 kept) and `pytest` (94 passed) all clean; coverage of `take_jobs/domain/*` is 100%.
