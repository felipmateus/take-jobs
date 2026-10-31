---
provider: manual
pr:
round: 7
round_created_at: 2026-10-31T00:56:07Z
status: resolved
file: src/take_jobs/infrastructure/scraping/spiders/base.py
line: 185
severity: medium
author: claude-code
provider_ref:
---

# Issue 002: Term whose request Scrapy drops silently is recorded as success

## Review Comment

`build_outcomes` (`spiders/base.py:185-195`) treats every term with `error is None` as successful when the close reason is `finished`, **even when the term never finished**: `unfinished_error = None`. A term can be unfinished at a `finished` close when Scrapy drops its request without calling the errback. This is the default `RFPDupeFilter` case, and the spider's requests do not set `dont_filter`. The result row then says `success` with `pages=0` (or fewer pages than were actually walked), and the failure is invisible in the run history and in O5.

Reproduced locally (loopback fixture server only, real `ScrapyJobScraper`):

1. **Colliding slugs.** Terms are not normalized or deduplicated by slug: `Settings._split_csv` only strips, and the spider's `dict.fromkeys(terms)` dedupes exact strings. With `["python", "Python"]`, the server sees only one request per URL, and the outcomes are:
   ```
   vagas     'Python'  pages=0 jobs=0 error=None
   infojobs  'Python'  pages=0 jobs=0 error=None
   ```
   Realistic configurations hit this: `desenvolvedor c#` and `desenvolvedor c++` both slug to `desenvolvedor-c`; `desenvolvedor .net` and `desenvolvedor net` collide in the same way. The default terms do not collide.
2. **A follow-up redirected to an already-fetched URL** (for example an Infojobs `?page=2` that answers 302 to `?page=1`). The redirected request is dupe-filtered, and the term ends `pages=1`, `success`, with the walk silently truncated.

This contradicts the intent stated in `build_outcomes`' own docstring ("a stopped crawl is never read as success") and the spec's close-reason mapping (`"finished"` → "per-term outcomes **as recorded**"; an unfinished term has no recorded outcome). `expected_combinations` counts `len(set(terms))`, so O5's denominator includes the phantom combination and its numerator counts it as a success.

Suggested fix:
- In `build_outcomes`, give an unfinished term at a `finished` close an explicit error, e.g. `crawl closed: finished before the term completed`, instead of `None`.
- Prevent the collision at its source: reject or collapse terms whose slugs collide, either in `Settings` validation (exit `2` with the colliding terms named) or in the spider, by mapping both terms to one state and one request.
- Add UT cases for both triggers (duplicate slug; redirect to a seen URL).

## Triage

- Decision: `VALID`
- Notes:
  - Reproduced by the tests added here (they failed before the fix): a term whose request Scrapy drops without an errback stayed `finished=False` and `build_outcomes` mapped `error=None` at a `finished` close, so it was recorded `success` with `pages=0` (or a truncated walk).
  - Root cause, two parts. (1) Distinct terms with one slug (`python`/`Python`, `desenvolvedor c#`/`c++`, `.net`/`net`) hit the same URL, and the dupe filter drops the second. (2) `build_outcomes` trusted `finished` as proof that every term completed.
  - Choice for (1): reject at config validation (exit 2), not merge in the spider. `c#` and `c++` cannot be kept distinct, because neither site's URL has a symbol-aware slug, so no spider-side mapping can make them separate combinations; merging would silently drop a term the maintainer asked for, against the fail-fast config policy. `Settings.scrape_terms` now raises `terms 'a', 'b' all search for '<slug>'; keep only one` (names both) and `term '###' has no letters or digits` (an empty slug would request `/vagas-de-`). Exact repeats stay accepted and collapse as before.
  - Fix for (2): at a `finished` close an unfinished term now gets `crawl closed: finished before the term completed`. This covers the redirect-to-a-fetched-URL trigger and any caller that bypasses `Settings`.
  - Tests: `tests/unit/test_config.py` (four collision cases, empty slug, exact repeat), `tests/unit/scraping/test_scraper_child.py` (`test_finished_reason_fails_a_term_that_never_finished`, real crawl with a 302 to an already fetched URL, real crawl with `python`/`Python`). The three scraper tests fail with the old `unfinished_error = None` and pass now.
  - Contract change (minimal): `_spec.md` close-reason mapping and Config Lifecycle validation list, `_dx.md` and README `SCRAPE_TERMS` rows.
- Verified (round 8): `Settings._distinct_slugs` (`src/take_jobs/config.py:147-163`) groups `dict.fromkeys(terms)` by `normalize(term)`, which equals the slug key because `slugify_term` only joins `normalize(term).split()` with `-`, so every URL collision is caught; it rejects an empty slug and names both terms. `build_outcomes` gives an unfinished term at a `finished` close `crawl closed: finished before the term completed`. `test_finished_reason_fails_a_term_that_never_finished`, `test_real_crawl_redirect_to_an_already_fetched_url_fails_the_term` and `test_real_crawl_terms_with_one_slug_never_read_as_success` pass (110 passed in the focused run). `_spec.md` (close-reason comment, Config Lifecycle), `_dx.md` and the README `SCRAPE_TERMS` row agree with the code.
