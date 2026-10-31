# task_04 memory

## Outcome
Completed. `take_jobs.infrastructure.scraping` has `slug`, `parsers/{common,vagas,infojobs}`, `spiders/{base,vagas,infojobs}`, `registry`, `settings`, `scraper`. Test seams: `tests/support/{socket_guard,fixture_server,child_targets,spiders}.py`. Fixtures in `tests/fixtures/html/`. 64 new unit tests (`tests/unit/scraping/`), full suite 158 passed.

## Fixture capture (subtask 4.1, 2026-10-30, honest UA `take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)`)
- robots.txt of both sites fetched first (200). Neither disallows `/vagas-de-*` or `/vagas-de-emprego-*`. At least 1.2 s between requests; about 60 requests in total. **Neither site blocked or degraded the honest UA** (no 403 on listings, no challenge page); no UA switch was made.
- Slugs: every one of the 12 default terms returns 200 with a listing page on both sites with `slugify_term` (so R2 is closed; no per-source slug function needed, including `desenvolvedor-net`).
  - vagas.com cards on page 1: desenvolvedor 10, programador 40 (+next), engenheiro-de-software 8, backend 2, frontend 1, full-stack 3, mobile 2, python 1, java 6, javascript 3, net 5, php 0 (a "Não encontramos resultados" page: a legitimate success with 0 jobs, US-005.EC-4). Only `programador` and `python` (the fixtures' term, 40 + 3) have more than one page.
  - Infojobs page 1: 20 cards for every term except desenvolvedor-frontend (17).
- vagas.com facts the spec did not have:
  - The follow-up page needs **session cookies** from page 1 as well as `X-Requested-With` + `Referer`: the same XHR URL fetched without the cookie jar returned a "no results" page for `programador` (and 3 cards for `python`, which is the real last page). Scrapy's default cookie middleware covers it; do not set `COOKIES_ENABLED=False`.
  - The XHR response is a **full HTML page**, not a fragment (the parser works on both). Without `X-Requested-With` the follow-up is 403.
  - Live `vagas-de-desenvolvedor` has a single page of 10 cards (see "Review round 7" below: the site itself says so). The fixture that held **page 2 of `programador`** (40 cards, `#maisVagas` -> `?pagina=3&q=programador`) is now named `vagas_programador_p2_xhr.html`.
- Fixtures (trimmed: scripts, styles, svg, comments, head and chrome removed; the listing markup is untouched): `vagas_python_p1.html` (40 cards, `#maisVagas`), `vagas_python_p2_xhr.html` (3 cards, last page), `vagas_programador_p2_xhr.html` (page 2 of `programador`), `infojobs_python_p1.html` (20 cards; first job is `11911899` "Desenvolvedor Python", ISLA, exactly as UT-034), `empty_listing.html` (vagas "no results" section of `desenvolvedor-php`; also parses to 0 jobs with the Infojobs parser).
- Synthetic for task_07: `journey_vagas_desenvolvedor.html` (jobs 9000001 "Desenvolvedor Backend Java", 9000002 "Desenvolvedor Frontend React Junior") and `journey_vagas_programador.html` (9000001 again, 9000003 "Programador de CNC", 9000004 "Programador Python Pleno"). `tests.support.fixture_server.journey_routes()` serves them and answers Infojobs with `empty_listing.html`, so only vagas contributes jobs.

## Decisions
- `ScrapeSettings` is a `Protocol` in `scraping/settings.py` (`scrape_max_pages`, `scrape_download_delay`, `scrape_user_agent`, `scrape_run_timeout_minutes`, `log_level`), because `infrastructure.scraping` may not import `take_jobs.config`; `config.Settings` fits it structurally.
- Parsers skip a card without id, title **or href** (a `ScrapedJob.url` cannot be null). NUL is stripped from the raw HTML before parsing and again per field. Infojobs `location`/`description` use exact-class direct children (`div[@class="mb-8"]`, `div[@class="text-medium"]`), not the loose `div.mb-8`/`div.text-medium`, which also match the attribute row and the date. `ListingPage` lives in `parsers/common.py`.
- Spiders: shared `ListingSpider` in `spiders/base.py`; the spider yields only ids unseen for the term and also appends them to `states[term].jobs` (the child builds the report from `spider.states`, `build_outcomes` is the pure close-reason mapping). Off-origin follow-ups are recorded by the spider (no exception), then no request. Duplicate terms collapse into one state. `start_requests()` is the sync generator named in UT-041; `start()` delegates to it.
- Scrapy 2.19 deprecates `RANDOMIZE_DOWNLOAD_DELAY`. UT-048 requires it, so it stays `False` and `DOWNLOAD_DELAY_JITTER=0` is added (the default jitter is +-50%, i.e. below 1 s). The one deprecation warning is filtered in the child. Also `TELNETCONSOLE_ENABLED=False`, `REMOTE_CONTROL_ENABLED=False` (it warned under a non-asyncio reactor), `LOG_LEVEL` WARNING unless DEBUG.
- Scraper: `_CHILD_TARGET` module global (looked up per `scrape()`) is the seam for replacing the child; `ScrapyJobScraper._terminate` sends SIGTERM, waits on the sentinel up to 5 s, then SIGKILL, and never reaps (the `scrape()` thread joins). The lock is an `RLock` so `interrupt()` can run inside a signal handler in the scraping thread. A report followed by a non-zero exit, or a non-`ScrapeReport` object, is `ScrapeCrashedError`.
- Child exit code asserted by tests: -15 (SIGTERM) for both the fake and the real crawl child, so Scrapy installs no handler and `interrupt()` never needs SIGKILL.
- `install_test_socket_guard(allow_hosts=None)` default allow-list is loopback; it never undoes itself (child process use). Verified that Twisted's `connect_ex` raise surfaces as a normal download failure: the outcome error is `SocketConnectBlockedError: ...` and the server sees 0 hits.

## Handoff for later tasks
- task_06 (IT-007/IT-013): `FixtureServer(routes, robots_txt=...)`, `Route(body, status, delay_s, require_xhr)`, `python_routes(delay_s=...)`, `server.first_listing_hit` (Event), `server.hits`, `server.listing_hits()`. `python_routes()` serves infojobs `page=2` as page 1 again (as the live site does). `build_cli_deps` must pass `child_initializer` to `ScrapyJobScraper(sources, settings, child_initializer=...)`; `ScrapyJobScraper(SOURCES, Settings())` works as is.
- task_07 (E2E): use `journey_routes()` and the fixtures above; journey pages are vagas-only by design.
- Per-site timing (>= 1 s between requests) is a settings contract only; a real `python` scrape of both sites takes about 3-5 s with the fixture server.

## Evidence
`uv run ruff format --check`, `ruff check`, `lint-imports` (8 kept) and `pytest` (158 passed, 33 s) all clean. Scraping unit tests: 64 (parsers 17, spiders 26, child/guard 21). IT-007 and IT-013 (database) stay with task_06.

## Review round 7 (reviews-007), live checks of 2026-10-30 (honest UA, robots.txt first, >= 1 s apart, about 35 requests in total, no block, no UA switch)

### Infojobs pagination (issue 001): `?page=N` HTML never paginated
- `GET /vagas-de-emprego-desenvolvedor.aspx?page=2` returns the **same 234354-byte page as `?page=1`** (20 identical ids), also with page 1's cookie jar plus `Referer`, and also with `X-Requested-With`. No 30x. The page-1 HTML has no pager markup at all: it has `#hdn_infinitescrolldesktop=true`, `#hdn_ListURL` and a `.js_infiniteScrollLoading` spinner.
- The site's `list.*.js` (`ncdn.infojobs.com.br/mf-publicarea/js/list.d7d8f45ad48e36c59b02.js`) shows the mechanism: on scroll it takes `#hdn_ListURL`, sets `page=N`, and does `fetch("/mf-publicarea/VacancyList/GetVacancyListFragment?url=" + encodeURIComponent(listURL))`, then appends `listFragmentHTML` of the JSON answer `{"eof": bool, "listFragmentHTML": "..."}`. Not disallowed by robots.txt (`/App_WebServices` is, `/mf-publicarea` is not).
- That endpoint works with the honest UA, **no cookie, no `Referer`, no `X-Requested-With`**. `desenvolvedor`: pages 2, 3, 4, 10, 12, 13 and 14 answer 20 unseen cards each (no overlap with page 1 or with each other); page 15 and every later page answer `{"eof":true,"listFragmentHTML":""}` (34 bytes). So the term has 14 pages (about 280 jobs), and `eof` is only `true` on the empty page. `python`: pages 2-4 all full.
- Real scraper check (`SCRAPE_MAX_PAGES=3`, term `desenvolvedor`): infojobs `pages=3`, 60 unique jobs, no error; vagas `pages=1`, 10 jobs.
- Fix: `InfojobsSpider` asks page 1 as HTML and pages 2+ at the fragment endpoint; `infojobs.parse_listing` accepts both bodies (JSON when the body starts with `{`). Fixtures `infojobs_python_p{2,3}_fragment.json` and `infojobs_fragment_eof.json`; `python_routes()` serves pages 2-4 through `fragment_target()` (the server reduces the `url=` origin before matching). The old "page 2 = page 1" assumption is gone from the tests and from `_spec.md`.

### vagas.com `desenvolvedor` (issue 003): the site really lists 10
- `GET /vagas-de-desenvolvedor`: 200, no redirect, canonical URL is itself, `<h1>10 vagas de emprego para desenvolvedor</h1>`, 10 cards, no `#maisVagas`. For comparison, the same day: `programador` "1136 vagas" (40 cards + `#maisVagas`), `python` "43 vagas" (40 cards + `#maisVagas`). The XHR `?pagina=2&q=desenvolvedor` (cookies, `X-Requested-With`, `Referer`) answers 200 with no cards; the non-XHR `?q=desenvolvedor` answers 403, as every non-XHR follow-up does.
- The site's own search form posts to `/vagas/pesquisas`, which robots.txt disallows (`Disallow: /vagas/pesquisas`), so it was **not** fetched; the count could not be compared with the site's own search. The landing page is the canonical SEO URL for the term, its own count says 10, and the titles are developer roles, so the URL is right and the `success` rows are honest.
- Fix: no spider change. `vagas_desenvolvedor_p1.html` (trimmed real page, with the `<h1>`) is a new fixture and the substitute fixture is renamed `vagas_programador_p2_xhr.html` (tests, `_tests.md`, `task_04.md` updated).

### Terms and unfinished terms (issue 002)
- `Settings.scrape_terms` rejects two different terms with the same `normalize()` form (`python`/`Python`, `c#`/`c++`, `.net`/`net`) naming both, and a term with no letters or digits (CLI exit 2). Chosen over a spider-side merge because `c#` and `c++` cannot be told apart by either site's slug, so no spider could keep them distinct; failing fast follows the config policy. Exact repeats are still accepted (they collapse).
- `build_outcomes` gives an unfinished term at a `finished` close the error `crawl closed: finished before the term completed` (covers a redirect to an already fetched URL and any direct caller that bypasses `Settings`).

### Test infrastructure
- IT-014 seeds and queries on one connection in one never-committed transaction (`now()` is the same for every statement), so the São Paulo midnight flake is gone (issue 004).
- `_start_postgres` retries only `ConnectionError("Port mapping ...")`, warns per swallowed attempt and chains the last error to the first; any other error propagates at once (issue 005; `tests/unit/test_container_start_retry.py`, with a fake container).
