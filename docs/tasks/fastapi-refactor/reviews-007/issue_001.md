---
provider: manual
pr:
round: 7
round_created_at: 2026-10-31T00:56:07Z
status: resolved
file: src/take_jobs/infrastructure/scraping/spiders/infojobs.py
line: 25
severity: high
author: claude-code
provider_ref:
---

# Issue 001: Infojobs never paginates live; page-2 request is unverified

## Review Comment

**Failure (runtime evidence, MAN-001 in `memory/task_09.md`).** In the live run, every Infojobs term stopped at `pages=2` and every combination was recorded `success`. `memory/task_04.md` reports that page 1 held **20 cards (a full page) for 11 of the 12 terms**; only `desenvolvedor frontend` had 17. Under rule 17, a full page 1 followed by "page 2 brought no unseen id" means page 2 returned page 1's ids. For broad terms such as `desenvolvedor` and `programador`, that cannot be the real end of the list. Infojobs therefore contributes at most 20 jobs per term, not up to `SCRAPE_MAX_PAGES` pages. This violates US-006.AC-2 and FR-08's intent, and the run history reports it as success, so O5 and the maintainer cannot see it.

**What the spider sends for page N** (`spiders/infojobs.py:19-26`, `spiders/base.py:102-109`):
- `GET {base_url}/vagas-de-emprego-{slug}.aspx?page=N`, built from `states[term].pages + 1`; the arithmetic is correct (UT-044).
- `follow_headers` is empty, so there is no `X-Requested-With`, unlike vagas.com, which needs it and answers 403 without it.
- `Referer` is the page-1 URL, set by Scrapy's RefererMiddleware.
- Cookies come from the spider's shared cookie jar.
- The User-Agent is the honest bot UA.

**Why the suite cannot catch this:** the `?page=N` mechanism for N ≥ 2 was never verified anywhere.
- `_spec.md` › External References says only `...python.aspx?page=1` was inspected. `task_04` memory records only page-1 card counts.
- The only Infojobs fixture, `infojobs_python_p1.html`, was trimmed to the `js_vacanciesGridFragment` block. All pagination markup (pager links, `data-page`, any XHR or postback hook) was removed, so the repository holds no evidence of how the site links page 2. The class name `js_vacanciesGridFragment` suggests that the grid is replaced by a JS-loaded fragment, as on vagas.com.
- The tests encode "page 2 = page 1" as the truth: `tests/support/fixture_server.py:141-142` serves page 1 for `?page=2`, and UT-043 (`tests/unit/scraping/test_spiders.py:122`) feeds page 1 back as page 2. No test, fixture or IT ever has an Infojobs page 2 with unseen ids, so the suite cannot distinguish "pagination works" from "pagination never works".

**Hypotheses ruled out locally** (loopback server only, real `ScrapyJobScraper`; scripts in the reviewer's scratchpad):
- *Cross-term session bleed through the shared cookie jar.* Scrapy attaches cookies when a request is enqueued, right after that term's own page-1 response. Both a cookie-value session model and a server-side session-id model still paginated all three terms to page 4.
- *A redirect of `?page=2` to the identical page-1 URL.* Scrapy's dupefilter drops the redirected request, so the term ends with `pages=1`. Live showed `pages=2`, so page 2 was actually parsed: either the server ignored `page`, or it redirected to a *different* URL that serves page 1 (for example the canonical URL without `?page`).

**Live checks needed** (the reviewer did not access the site; the fixer or user must run these once, at the honest UA and ≥ 1 s apart):
1. Save the **untrimmed** HTML of `https://www.infojobs.com.br/vagas-de-emprego-desenvolvedor.aspx?page=1`. Record the pager markup and the exact href or parameters for page 2: parameter name and case (`page`/`Page`/other), any extra parameters, and whether a postback or JS hook is used.
2. In a browser's devtools, click "next page" and record the request: method, URL, query, `X-Requested-With`, `Referer` and cookies, and whether the response is a fragment for `js_vacanciesGridFragment`.
3. Fetch `?page=2` with the honest UA and check for a 30x and the final URL (`curl -sIL`, or run the scraper with `LOG_LEVEL=DEBUG` and look for `Redirecting (30x)`). Then compare the `data-id` sets of page 1 and page 2: (a) bare; (b) with page 1's cookie jar and `Referer`; (c) with `X-Requested-With: XMLHttpRequest`.
4. If only a browser-like UA gets real page 2 content, **stop and return to the user** (OQ-1). Do not switch the UA silently.

**Fix once the mechanism is known:**
- Build the page-N request the way the site does: URL, parameters and headers, setting `follow_headers` if needed.
- Capture a real page-2 fixture with unseen ids.
- Add a spider unit test where page 2 brings unseen ids and requests page 3.
- Change `python_routes()` so that Infojobs page 2 differs from page 1 and page 3 repeats it. IT-007 then proves that the walk goes past page 2.
- Record the verified mechanism in `memory/task_04.md` and `_spec.md` › Integration Points.

Optional hardening (non-blocking): log a warning when page 2 repeats a *full* page 1, so this degradation shows up in the logs rather than as a silent success.

## Triage

- Decision: `VALID`
- Notes:
  - Live checks (2026-10-30, honest UA, robots.txt first, >= 1 s apart; no block, no UA switch, so OQ-1 does not apply). `?page=2` HTML returns byte-for-byte page 1 (234354 bytes, the same 20 ids), bare, with page 1's cookies and `Referer`, and with `X-Requested-With`; no redirect. The untrimmed page 1 has no pager markup, only `#hdn_infinitescrolldesktop=true`, `#hdn_ListURL` and a `.js_infiniteScrollLoading` spinner. The site script (`list.d7d8f45ad48e36c59b02.js`) loads more results with `fetch("/mf-publicarea/VacancyList/GetVacancyListFragment?url=" + encodeURIComponent(<listing URL with page=N>))` and appends `listFragmentHTML` from the JSON `{"eof", "listFragmentHTML"}`. That endpoint works with the honest UA and no cookie, `Referer` or `X-Requested-With`; `desenvolvedor` pages 2-4, 10 and 12-14 return 20 unseen cards each, page 15+ returns `{"eof":true,"listFragmentHTML":""}`. `python` pages 2-4 are also full.
  - Root cause: the spider built `?page=N` HTML URLs, which the site ignores, so "page 2" was page 1 and rule 17 ended every term at `pages=2` as `success`. The fixture and tests encoded that wrong behavior. The reviewer's hypotheses (cookie bleed, redirect) were correctly ruled out; the real cause is the URL mechanism.
  - Fix: `InfojobsSpider` requests page 1 as HTML and pages 2+ at the fragment endpoint (`url=` percent-encoded like `encodeURIComponent`, off-origin check unchanged); `infojobs.parse_listing` accepts the JSON body (first char `{`) and raises `ValueError` on a JSON body without `listFragmentHTML`, which becomes a rule 28 parse error. Real fixtures captured: `infojobs_python_p2_fragment.json`, `infojobs_python_p3_fragment.json`, `infojobs_fragment_eof.json`. `python_routes()` now serves Infojobs pages 1-4 (the fixture server reduces the `url=` origin so routes stay port-independent); the "page 2 = page 1" route is gone.
  - Tests: UT-043 now walks page 1, 2, 3 and the end (pages 4, 60 jobs, each page requests the next fragment URL) and keeps a repeated-page stop case; UT-044 expects the fragment URL; new parser tests for the fragment body and bad shapes; new real-crawl tests (IT-007 equivalent `test_real_crawl_collects_both_sources...` now asserts infojobs `pages == 4`, 60 jobs; `test_real_crawl_infojobs_follow_ups_use_the_fragment_endpoint` asserts the exact requests). A real run against the live sites (`SCRAPE_MAX_PAGES=3`, `desenvolvedor`) gave infojobs `pages=3`, 60 unique jobs, no error.
  - Contract change (minimal): `_spec.md` > Integration Points row for infojobs, `_tests.md` (fixtures list, UT-043, IT-007), `memory/task_04.md` and `memory/MEMORY.md` updated. No new config key.
  - Not done: the optional "warn when page 2 repeats a full page 1" hardening; with real pagination a repeat is no longer the expected end signal, and the unfinished-term fix of issue 002 covers dropped requests.
- Verified (round 8): `InfojobsSpider.next_page_url` builds `{base_url}/mf-publicarea/VacancyList/GetVacancyListFragment?url=<quote(listing URL ?page=N, safe='')>` and `parsers/infojobs.parse_listing` reads `listFragmentHTML` from a JSON body (missing key -> `ValueError` -> rule 28 parse error). The fixtures are real: p2/p3 fragments each hold 20 unique `data-id`s disjoint from page 1 and `eof=false`; the eof fixture is `{"eof":true,"listFragmentHTML":""}`. `python_routes()` no longer serves page 1 for page 2. UT-043 walks 1->2->3->eof (`pages == 4`, 60 jobs) and keeps the repeat-stop case; UT-044 expects the fragment URL; `test_real_crawl_infojobs_follow_ups_use_the_fragment_endpoint` asserts the exact request sequence through the real `ScrapyJobScraper`. Ran `pytest tests/unit/scraping tests/unit/test_config.py tests/unit/test_container_start_retry.py` -> 110 passed; `test_it007_two_full_cycles_in_one_process` passed against Docker. The `_spec.md` Integration Points row matches the code. Remaining gap: the named IT-007 test does not assert the new contracted `pages == 4` (tracked as round 8 issue 001, low).
