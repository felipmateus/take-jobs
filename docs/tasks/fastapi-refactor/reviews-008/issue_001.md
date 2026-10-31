---
provider: manual
pr:
round: 8
round_created_at: 2026-10-31T01:25:34Z
status: resolved
file: tests/integration/test_collect_cli.py
line: 73
severity: low
author: claude-code
provider_ref:
---

# Issue 001: _tests.md drifted from the suite after the round-7 fixes

## Review Comment

The round-7 fixes edited `_tests.md`, but the catalog and the suite now disagree in two places. The behavior is tested and passes in both places; the gap is test-contract parity and traceability, so this is non-blocking.

**1. IT-007 is contracted to prove Infojobs pagination, but the IT-007 tests do not assert it.**
- `_tests.md:460` (IT-007) now says: "the Infojobs outcome has `pages == 4` and 60 jobs (the walk goes past page 2)". Round 7 issue 001 asked for exactly this ("IT-007 then proves that the walk goes past page 2").
- `test_it007_two_full_cycles_in_one_process` (`tests/integration/test_collect_cli.py:73-74`) asserts only `{...}["vagas"] == 2` and `error is None`. `test_it007_two_collect_commands_in_one_process` asserts only statuses and result counts. Neither checks Infojobs `pages` or job count.
- The assertion lives only in the unit-level `test_real_crawl_collects_both_sources_and_can_run_twice_in_one_process` (`tests/unit/scraping/test_scraper_child.py:290-291`). The coverage matrix rows US-001.AC-3, US-006.AC-4 and "Spiders" cite IT-007 for paging. If the Infojobs walk regressed to stop at page 2 (the original round-7 failure mode), IT-007 would still pass.
- Evidence: I read both IT-007 tests; `pytest "tests/integration/test_collect_cli.py::test_it007_two_full_cycles_in_one_process"` passes, and it contains no Infojobs-pages assertion.

**2. The two behaviors added by round 7 issue 002 have no catalogued test.**
- `_spec.md:954` adds a `SCRAPE_TERMS` validation rule (distinct slugs, no empty slug, exit `2`). `_spec.md:668-670` adds the `finished` close-reason mapping (`crawl closed: finished before the term completed`).
- `_tests.md` has no ID for either. UT-022 and UT-073 cover only the empty value, and UT-106 covers only `closespider_timeout`. The matching tests exist without IDs: `tests/unit/test_config.py` (collision cases), `test_finished_reason_fails_a_term_that_never_finished`, `test_real_crawl_redirect_to_an_already_fetched_url_fails_the_term` and `test_real_crawl_terms_with_one_slug_never_read_as_success`. No coverage-matrix row points at them, so a later change could drop them without any contract noticing.

**Suggested fix:**
- In `test_it007_two_full_cycles_in_one_process`, add `assert by_source["infojobs"].pages == 4` and the 60-job count. Building `by_source` from `report.outcomes` is enough. Alternatively, reword IT-007 in `_tests.md` and point the coverage rows at the unit real-crawl test, but the assertion is the cheaper and stronger choice.
- Extend UT-022 (or add a new UT) for the slug-collision and empty-slug cases, plus the exit-`2` path. Extend UT-106 with the `finished` reason. Reference them in the matching coverage-matrix rows (Config, Scraper child).

## Triage

- Decision: `VALID`
- Notes:
  - Root cause: round 7 added the Infojobs paging contract to `_tests.md` IT-007 and two behaviors (slug collision rejected at config validation; `finished` close reason) without extending the suite's IT-007 assertions or giving the new tests IDs and matrix rows. Confirmed by reading both IT-007 tests (no Infojobs `pages` or job-count assertion) and by grepping `_tests.md` (no ID for either behavior).
  - Fix (a): `tests/integration/test_collect_cli.py::test_it007_two_full_cycles_in_one_process` now builds `by_source` from `report.outcomes` and asserts `infojobs.pages == 4` and `len(infojobs.jobs) == 60`, beside the Vagas `pages == 2`.
  - Fix (b), new IDs (unique, each present in the matrix):
    - **UT-118** (Config): the slug-collision, no-letters-or-digits and repeated-term cases in `tests/unit/test_config.py` (renamed `test_ut118_*`, docstrings cite the ID). Matrix rows: US-003.EC-3 and Config.
    - **UT-073** extended: new `test_ut073_terms_with_the_same_slug_exit_2_naming_both` in `tests/unit/cli/test_collect.py` covers the exit `2` path for a collision (no CLI test existed for it). Already in the US-003.EC-3 row.
    - **UT-119** (Scraper child): the `finished` close-reason tests in `tests/unit/scraping/test_scraper_child.py` (unit mapping and the two real-crawl cases), renamed `test_ut119_*`, module docstring updated. Matrix row: Scraper child.
  - `_tests.md`: UT-118 and UT-119 defined, UT-073 extended, three matrix rows updated. A script check found 130 unique UT/IT IDs, all present in the matrix.
  - Verification: `ruff format --check && ruff check && lint-imports && pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80` passed: 463 passed, coverage 99.55%.
- Verified: (review round 9, 2026-10-31T01:34:43Z) Fix confirmed. `test_it007_two_full_cycles_in_one_process` (`tests/integration/test_collect_cli.py:73-77`) now asserts `infojobs.pages == 4` and 60 jobs beside Vagas `pages == 2`, matching `_tests.md` IT-007. `_tests.md` defines UT-118 (Config, line 210) and UT-119 (Scraper child, line 378) and extends UT-073 (line 287). The matrix rows US-003.EC-3, Config and Scraper child cite them. The suite has `test_ut118_*` (3, `tests/unit/test_config.py`), `test_ut119_*` (4, `tests/unit/scraping/test_scraper_child.py`) and `test_ut073_terms_with_the_same_slug_exit_2_naming_both` (`tests/unit/cli/test_collect.py:316`), and each asserts its catalogued behavior. Ran `.venv/bin/python -m pytest tests/unit/test_config.py tests/unit/cli/test_collect.py tests/unit/scraping/test_scraper_child.py -k "ut118 or ut119 or ut073"`: 13 passed. Ran `tests/integration/test_collect_cli.py -k it007` (Docker): 2 passed, and no containers were left behind. A script found 130 UT/IT IDs defined. One follow-on gap: no task in `_tasks.md` owns the new IDs. It is tracked as `reviews-009/issue_001.md`.
