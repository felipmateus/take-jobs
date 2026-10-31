# Test Specification: take-jobs v2

Canonical test contract for take-jobs v2. Companion to `_spec.md`.
Derived from `_user_stories.md` (behavior), `_spec.md` Part II (components) and `_dx.md` (CLI/API journeys). No UI, so `_uiux.md` does not apply.

## Strategy

- **Frameworks and harnesses:**
  - pytest, pytest-asyncio (`asyncio_mode=auto`, session-scoped loop), pytest-cov.
  - httpx `AsyncClient` + `ASGITransport` for the API.
  - testcontainers `PostgresContainer("postgres:17")`, one per session, with `alembic upgrade head` applied once. Each test runs in a transaction that is rolled back, or truncates tables when the code under test commits.
  - A local fixture HTTP server (stdlib `http.server` on a thread), serving `tests/fixtures/html/` plus an allow-all `robots.txt`, for the scraper ITs and E2Es. It can delay responses or answer with a chosen status per path. Tests point sources at it with `with_base_url(SOURCES, server_url)` (`_spec.md` › Core Interfaces); no configuration key exists for this.
  - E2E tests are **synchronous**. They call `main([...], deps=build_cli_deps(settings, sources))` and query `create_app(settings, sources)` through `fastapi.testclient.TestClient`. The crawl runs in its spawned child, so `collect` can be called many times per session (ADR-002).
  - Network guard: `pytest-socket` with `--disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,::1,localhost,<testcontainers host>` in the session config. The spawned crawl child does not inherit the guard. Every test that crawls therefore builds its scraper with `child_initializer=install_test_socket_guard` (a top-level function in `tests/support/`), which installs the same guard inside the child. With the URL-resolution rule (`_spec.md` › Integration Points), this enforces FR-30 in the process that makes the requests.
- **Fakes at I/O boundaries only:**
  - Repositories, UoW, probe: in-memory implementations in `tests/fakes.py`.
  - `Clock`: `FixedClock`.
  - `JobScraper`: returns a canned `ScrapeReport`.
  - Process runner: records argv.
  - Rules, services, parsers and spiders are never faked.
- **Fixtures:** trimmed copies of live listing pages captured in task 3:
  - `vagas_python_p1.html`: the full first page, with 40 cards and `#maisVagas`.
  - `vagas_python_p2_xhr.html`: the raw XHR response for page 2, fetched with `X-Requested-With`. It is the last page, with no `#maisVagas`.
  - `vagas_programador_p2_xhr.html`: the raw XHR response for page 2 of a term with more pages (`programador`); it has a `#maisVagas` for page 3. Renamed from `vagas_desenvolvedor_p2_xhr.html`, which never held `desenvolvedor` (review round 7, issue 003).
  - `vagas_desenvolvedor_p1.html`: the real `desenvolvedor` page, "10 vagas de emprego para desenvolvedor", 10 cards and no `#maisVagas`.
  - `infojobs_python_p1.html` (20 cards).
  - `infojobs_python_p2_fragment.json`, `infojobs_python_p3_fragment.json`: the list-fragment JSON answers for Infojobs pages 2 and 3 (20 unseen cards each), and `infojobs_fragment_eof.json`, the answer past the end of the list (review round 7, issue 001).
  - `empty_listing.html`.
  - Synthetic `journey_*.html` pages for the E2Es, containing known titles such as "Programador de CNC" and a job repeated across two terms.
- **Execution:**
  - `uv run pytest` runs everything. Docker is required for `IT-*` and `E2E-*`.
  - `uv run pytest -m "not integration"` runs the unit suite only.
  - `IT-011` is marked `perf` and also runs in CI.
- **Conventions:**
  - Unit tests mirror the package, e.g. `tests/unit/domain/test_rules.py`; integration tests go in `tests/integration/`, end-to-end tests in `tests/e2e/`.
  - Table-driven `pytest.mark.parametrize` with readable `ids`.
  - Test names state the behavior, e.g. `test_title_with_exclude_keyword_is_not_relevant`.

## Coverage Matrix

| Source | Behavior | Unit | Integration | E2E |
| --- | --- | --- | --- | --- |
| US-001.AC-1/AC-2 | Daily cron at the configured time and time zone | UT-083 | — | — |
| US-001.AC-3 | One result per source × term | UT-059 | IT-007 | E2E-001 |
| US-001.AC-4 | Stored job has all fields | UT-030, UT-034 | IT-002 | E2E-001 |
| US-001.EC-1 | Card without id or title skipped | UT-033, UT-035, UT-038 | — | — |
| US-001.EC-2 | Missing optional fields stored as null | UT-033 | IT-002, IT-003 | — |
| US-001.EC-3 | Missed slot recovered by start-up catch-up | UT-018, UT-067, UT-080 | — | — |
| US-001.EC-4 | No overlapping run | UT-083 (`max_instances=1`) | IT-009 | — |
| US-002.AC-1/2/3 | Insert, refresh, first_seen kept | — | IT-002 | E2E-002 |
| US-002.EC-1 | Same job in two terms counted new then seen_again | UT-060 | — | E2E-002 |
| US-002.EC-2 | Same id on two sources = two jobs | — | IT-002 | — |
| US-003.AC-1 | Manual collect prints lines and summary | UT-070 | — | E2E-001 |
| US-003.AC-2 | Exit 0 success/partial, 1 failed, 4 signal | UT-071, UT-104 | IT-013 | E2E-004 |
| US-003.AC-3 | `--json` output | UT-074 | — | E2E-001 |
| US-003.EC-1 | Run in progress → exit 3 | UT-072, UT-057 | IT-009 | — |
| US-003.EC-2 | Stale run (> 60 min) marked interrupted | UT-058 | IT-009 | — |
| US-003.EC-3 | Invalid config → exit 2 (also under Compose), including a `SCRAPE_TERMS` slug collision | UT-073, UT-022, UT-118 | IT-012 | — |
| US-003.EC-4 | DB unreachable → exit 1 | UT-076 | — | — |
| US-003.EC-5 | Signal (during or between phases) → failed, exit 4, next collect not blocked | UT-104, UT-107, UT-117 | IT-013 | — |
| US-003.EC-6 | Ingest failure → failed, exit 1 | UT-079 | IT-008 | — |
| US-003.EC-7 | Run taken over → exit 1 | UT-066, UT-105 | — | — |
| US-004.AC-1 / EC-1 | Startup run when store empty | UT-018, UT-080 | IT-010 | — |
| US-004.AC-2 | No startup run when a recent run exists | UT-018, UT-081 | IT-006 (`latest_finished`) | — |
| US-004.AC-3 | Flag disables startup run | UT-082 | — | — |
| US-004.AC-4 | Startup run when no run finished in 24 h | UT-018, UT-067, UT-080 | IT-006 | — |
| US-004.EC-2 | Stop during startup run → forwarded to the collector promptly; next start collects | UT-087, UT-088, UT-089, UT-117 (`start_run` case) | IT-013 | — |
| US-004.EC-3 | DB not ready at scheduler start → retry, exit 1 | UT-085 | — | — |
| US-005.AC-1 / EC-1 | Partial run keeps successful data | UT-061 | — | E2E-004 |
| US-005.AC-2 | All failed → failed | UT-062 | — | — |
| US-005.AC-3 | No same-run retry | UT-083 (the cron job is the only scheduled job; no retry path exists) | — | — |
| US-005.EC-2 | HTTP 403/5xx fails combination | UT-045 | — | E2E-004 |
| US-005.EC-3 | robots.txt block | UT-047 | — | — |
| US-005.EC-4 | Zero cards = success with 0 jobs | UT-036 | — | — |
| US-005.EC-5 | Crawl crash → run failed | UT-075, UT-063, UT-108 | — | — |
| US-005.EC-6 | Parse error fails only that combination | UT-049 | — | — |
| US-005.EC-7 | Crawl time limit → unfinished combinations failed | UT-106, UT-048 | — | — |
| US-006.AC-1 | ≥ 1 s between requests per site | UT-048 | — | — (timing not asserted; settings are the contract, ADR-003) |
| US-006.AC-2 / EC-2 | Page cap | UT-044 | — | — |
| US-006.AC-3 / EC-1 | Stop when no unseen ids | UT-043 | — | — |
| US-006.AC-4 | Stop when no next link, including the XHR follow-up pages; next page resolved against the page URL | UT-031, UT-032, UT-037, UT-042 | IT-007 | — |
| US-007.AC-1 | New source accepted by API and docs | UT-102 | — | — |
| US-007.AC-2 | New source produces outcomes | — | IT-007 | — |
| US-007.EC-1 | Unknown source → 422 | UT-093 | — | — |
| US-008.AC-1/2/3/5 | Relevance include, exclude, normalization | UT-003–UT-008 | — | E2E-002 |
| US-008.AC-4 | Lists come from configuration | UT-077 | — | — |
| US-008.EC-1 | Stored job turning irrelevant is not refreshed | UT-064 | — | — |
| US-008.EC-2 | Empty include list rejected | UT-009, UT-022 | — | — |
| US-009.AC-1/2 | Seniority levels and null | UT-010, UT-011 | — | E2E-001 |
| US-009.EC-1 | Left-most keyword wins | UT-012 | — | — |
| US-009.EC-2 | PL/SQL is not mid | UT-013 | — | — |
| US-010.AC-1/2 | Active-only by default | UT-050 | IT-004 | E2E-003 |
| US-010.AC-3 | `include_inactive` | UT-051 | IT-004 | E2E-003 |
| US-010.AC-4 | Reactivation | — | — | E2E-003 |
| US-010.AC-5 | Threshold configurable | UT-050 (parametrized `inactive_after`) | — | — |
| US-010.EC-1 | Exactly 7 days still active | UT-014 | — | — |
| US-010.EC-2 | Detail returns inactive job | UT-055 | — | E2E-003 |
| US-011.AC-1/2/3 | Text search on title, company, description, accent-insensitive | — | IT-003 | E2E-001 |
| US-011.EC-1 | Blank q ignored | UT-054 | — | — |
| US-011.EC-2 | Wildcards matched literally | — | IT-003 | — |
| US-011.EC-3 | q > 100 chars → 422 | UT-095 | — | — |
| US-011.EC-4 | No match → empty page | — | IT-003 | — |
| US-012.AC-1/2/3/4/5 | Filters and their combination | UT-103 | IT-004 | — |
| US-012.EC-1 | Inverted period → invalid_period | UT-052, UT-092 | — | — |
| US-012.EC-2 | Unknown seniority → 422 | UT-094 | — | — |
| US-012.EC-3 | Malformed date → 422 | UT-091 | — | — |
| US-012.EC-4 | Period + active rule combined | — | IT-004 | — |
| US-013.AC-1 | Default page and size | UT-090 | — | — |
| US-013.AC-2/3 | Order and offset | — | IT-005 | — |
| US-013.EC-1/2 | Page/size bounds | UT-091 | — | — |
| US-013.EC-3 | Page beyond last | UT-016 | IT-005 | — |
| US-013.EC-4 | Shifting pages during ingestion | No automated test: documented absence of a snapshot guarantee; no behavior to assert | — | — |
| US-014.AC-1 | Detail by id | — | — | E2E-001 |
| US-014.EC-1/2 | Unknown id 404, non-int 422 | UT-096 | — | — |
| US-015.AC-1/2 | Swagger UI and OpenAPI | UT-102 | — | — |
| US-016.AC-1/2 | Health ok / unavailable | UT-101 | IT-010 | E2E-005 |
| US-017.AC-1 | List runs with real totals | UT-017 | IT-006 | E2E-001 |
| US-017.AC-2 | Running run shown | — | IT-006 | — |
| US-017.EC-1 | No runs → empty | — | IT-006 | — |
| US-017.EC-2 | SIGKILLed run shown running until next start | — | IT-009 | — |
| US-018.AC-1 | Run detail with results | — | IT-006 | E2E-001 |
| US-018.AC-2 | Totals = sum of results | UT-017 | IT-006 | — |
| US-018.EC-1 | Unknown run → 404 | UT-065, UT-097 | — | — |
| US-018.EC-2 | Running run has empty results | — | IT-006 | — |
| US-019.AC-1 | One command, ordered start-up, healthcheck without warnings | UT-110 | — | MAN-001 |
| US-019.AC-2, EC-2, EC-3 | Real data ≤ 15 min, port conflict, restart keeps data and follows the 24 h rule | UT-080, UT-081 (EC-3 rule) | — | MAN-001 (needs real sites and Docker Compose) |
| US-019.EC-1 | Starts without `.env` | UT-020, UT-110 (no `env_file`) | IT-012 | MAN-001 |
| US-020.AC-1/2 | Every key read with default; `.env.example` complete | UT-020, UT-021 | IT-012 | — |
| US-020.AC-3 | No committed credentials | — | IT-012 (mechanical secret scan) | — |
| US-020.EC-1/2/3 | Invalid numeric, cron, time zone | UT-023, UT-025, UT-026, UT-027 | — | — |
| US-020.EC-4 | Empty exclude list passes through Compose | UT-022 | IT-012 | — |
| US-020.EC-5 | Standard cron day-of-week, including Sunday-first ranges | UT-019, UT-083 | — | — |
| US-021.AC-1 | CI gates on push and PR | UT-111 | — | MAN-004 (green run on GitHub) |
| US-021.AC-2 | No network to the real sites, including from the crawl child | UT-031, UT-039, UT-115, UT-116 | IT-007, IT-013 | E2E-001–E2E-004 |
| US-021.AC-3 | Coverage ≥ 80% gate | UT-111 | — | MAN-004 |
| US-022.AC-1 | README sections | UT-112 | — | MAN-005 |
| US-022.AC-2 | `v1` tag | UT-113 | — | MAN-005 |
| US-022.AC-3 | Artifacts present | UT-114 | — | MAN-005 |
| Domain rules (`_spec.md` › Business Rules 4–15) | Normalization, relevance, seniority, activity, run status, startup reason, cron | UT-001–UT-019 | — | — |
| Config (`_spec.md` › Config Lifecycle) | Parsing and fail-fast validation, including `SCRAPE_TERMS` distinct slugs | UT-020–UT-027, UT-118 | IT-012 | — |
| Parsers (`_spec.md` › Integration Points; rule 27) | Field mapping per source, XHR pages, sanitization, URL resolution and off-origin guard | UT-030–UT-039 | — | — |
| Spiders (ADR-003, rules 16–17, 28) | Terms, paging, stop, errors, settings | UT-040–UT-049 | IT-007 | — |
| Scraper child (ADR-002, rules 24–25) | Close reasons (incl. `finished` before the term completed), parent-decided interruption, crash without hang, large report without deadlock, network guard in child | UT-106–UT-109, UT-116, UT-119 | IT-007, IT-013 | — |
| Application services | Query and collection use cases, including the `before_commit` ordering | UT-050–UT-068 | IT-008 | — |
| CLI `collect` (`_dx.md` › CLI) | Output, `--json`, `--trigger`, exit codes 0/1/2/3/4, composition, single signal handler across phases | UT-070–UT-079, UT-104, UT-105, UT-117 | IT-009, IT-013 | E2E-001, E2E-004 |
| Scheduler (ADR-004) | Startup run, cron job, runner (`CollectionRunner`, polling, never `wait()`), probe retry, SIGTERM forwarding installed first, `python -m`, via the `cli.scheduler` seams | UT-080–UT-089 | — | — |
| API (`_spec.md` › API Endpoints; `_dx.md` › Errors) | Params, validation, error mapping (404/422/500/503), docs | UT-090–UT-103 | — | E2E-001–E2E-005 |
| Static repository contracts | Compose (incl. healthcheck), CI, README, tag, artifacts, network guard | UT-110–UT-115 | IT-012 (secret scan with self-check) | — |
| Persistence (`_spec.md` › Data Models) | Migrations, upsert, search, guard, totals | — | IT-001–IT-006, IT-010 | — |
| Safety Invariants 1–2 | Single running run; single finish; takeover error | UT-066 | IT-006 | — |
| Safety Invariant 3 | Atomic completion; ingest failure recorded | UT-079 | IT-008 | — |
| Safety Invariant 5 (R1, R6) | Crawl in spawned child; repeated collects in one process; report read before join | UT-108, UT-109 | IT-007 | E2E-002, E2E-003 |
| Safety Invariant 6 | No shell; `Popen` handle kept | UT-084, UT-086, UT-087 | — | — |
| Safety Invariant 7 | Per-site serialization | UT-048 | — | — |
| Safety Invariant 8 | Signal → failed within bound (`start_run`, crawl, Ctrl+C, ingest, between phases, during startup run); a post-commit signal leaves the finished run; never success-by-interruption or running | UT-087, UT-088, UT-089, UT-104, UT-107, UT-117 | IT-013 (a, b, c) | — |
| Safety Invariant 9 | Crawl bounded below takeover age | UT-048, UT-106 | — | — |
| Architectural Boundaries (ADR-001) | Import contracts | — | `lint-imports` CI gate, asserted present by UT-111 | — |
| O5 reliability metric | Query counts whole-run failures and missing days; excludes today | — | IT-014 (a, b) | MAN-002 (7 days of real operation) |
| O7 performance | p95 < 300 ms at 50k jobs, including 1–2 character queries | — | IT-011 | — |
| O6 relevance | Operational metric | — | — | MAN-003 |

## Unit Tests

### Domain rules (Spec: Business Rules, Core Interfaces › `rules.py`, `models.py`)

- **UT-001** (happy): `normalize("Desenvolvedor Sênior (Back-End) — São Paulo")` → `"desenvolvedor senior back end sao paulo"`.
- **UT-002** (boundary): `normalize("  ")` → `""`.
- **UT-003** (happy): default `RelevancePolicy.is_relevant("Desenvolvedor Python Pleno")` → `True`.
- **UT-004** (happy): default policy, `"Analista de Suporte"` → `False`.
- **UT-005** (happy): default policy, `"Programador de CNC"` → `False`.
- **UT-006** (boundary): default policy, `"PROGRAMADOR DE PRODUÇÃO"` → `False` (case and accents normalized, `producao` excluded).
- **UT-007** (boundary): default policy, `"Analista DevOps"` → `False` (`dev` matches whole words only).
- **UT-008** (happy): default policy, `"Engenheiro(a) Front-end React"` → `True` (`front-end` normalized to the phrase `front end`).
- **UT-009** (error): `RelevancePolicy(include=[], exclude=["cnc"])` → `ValueError("include keywords must not be empty")`.
- **UT-010** (happy): `classify_seniority`, parametrized: `"Estagiário de Desenvolvimento"`→`intern`, `"Desenvolvedor Jr"`→`junior`, `"Trainee Dev"`→`junior`, `"Dev Pleno"`→`mid`, `"Desenvolvedor Sênior"`→`senior`, `"Tech Lead Java"`→`senior`, `"Especialista .NET"`→`senior`.
- **UT-011** (happy): `classify_seniority("Desenvolvedor Python")` → `None`.
- **UT-012** (boundary): `classify_seniority("Desenvolvedor Júnior/Pleno")` → `junior`.
- **UT-013** (boundary): `classify_seniority("Desenvolvedor PL/SQL")` → `None`.
- **UT-014** (boundary): `Job.is_active(now, timedelta(days=7))` with `last_seen_at = now − 7d` → `True`; with `now − 7d − 1s` → `False`.
- **UT-015** (state): `final_run_status`, parametrized: `[success, success]`→`success`; `[success, failed]`→`partial`; `[failed, failed]`→`failed`.
- **UT-016** (boundary): `Page(items=(), total=0, page=1, size=20).pages` → `0`; `total=41, size=20` → `3`; `Page(items=(), total=41, page=5, size=20)` is valid (page beyond last).
- **UT-017** (happy): `RunTotals.from_results` with results `(new 3, seen 1, disc 2)` and `(new 0, seen 4, disc 1)` → `RunTotals(new=3, seen_again=5, discarded=3)`; with no results → all zeros.
- **UT-018** (boundary): `startup_collection_reason`, parametrized with now = `2026-10-30T12:00Z`:
  - `store_empty=True` → `"empty_job_store"`, whatever the latest run;
  - `store_empty=False, latest=None` → `"no_recent_run"`;
  - latest started `2026-10-29T11:59Z` (24 h 1 min ago) → `"no_recent_run"`;
  - latest `2026-10-29T12:00Z` (exactly 24 h) → `None`;
  - latest `2026-10-30T09:00Z` → `None`.
- **UT-019** (boundary): `to_standard_crontab`, parametrized:

  | Input | Output |
  | --- | --- |
  | `"0 6 * * *"` | unchanged |
  | `"0 6 * * 0"`, `"0 6 * * 7"` | `"0 6 * * sun"` |
  | `"0 6 * * 1-5"` | `"0 6 * * mon,tue,wed,thu,fri"` |
  | `"0 6 * * 0-4"` | `"0 6 * * sun,mon,tue,wed,thu"` |
  | `"0 6 * * 0-6"` | `"0 6 * * sun,mon,tue,wed,thu,fri,sat"` |
  | `"0 6 * * 5-7"` | `"0 6 * * sun,fri,sat"` |
  | `"0 6 * * */2"` | `"0 6 * * sun,tue,thu,sat"` |
  | `"0 6 * * sun-thu"` | `"0 6 * * sun,mon,tue,wed,thu"` |
  | `"0 6 * * 8"` | `ValueError` |

  Every non-error output is accepted by `CronTrigger.from_crontab`. From Fri 2026-10-30, the next fire time is Sun 2026-11-01 06:00 for `"0 6 * * 0"`, and Sun 2026-11-01 06:00 for `"0 6 * * 0-4"`.

### Config (Spec: Config Lifecycle)

- **UT-020** (happy): `Settings()` with an empty environment and no `.env` → `scrape_terms` has the 12 default terms in order, `scrape_cron == "0 6 * * *"`, `scrape_timezone == "America/Sao_Paulo"`, `scrape_on_start is True`, `scrape_run_timeout_minutes == 60`, `job_inactive_after_days == 7`, `scrape_max_pages == 20`.
- **UT-021** (boundary): `SCRAPE_TERMS=" desenvolvedor python , ,desenvolvedor go "` → `["desenvolvedor python", "desenvolvedor go"]`.
- **UT-022** (error): parametrized over `SCRAPE_TERMS=""` and `RELEVANCE_INCLUDE_KEYWORDS=""` → `ValidationError` whose message names the key; `RELEVANCE_EXCLUDE_KEYWORDS=""` → valid, empty list.
- **UT-118** (error): `SCRAPE_TERMS` slug rules (review round 7, issue 002; `_spec.md` › Config Lifecycle).
  - `python,Python`, `desenvolvedor c#, desenvolvedor c++`, `desenvolvedor .net,desenvolvedor net` and `Programação,programacao` → `ValidationError` naming `SCRAPE_TERMS` and both terms, such as `'python', 'Python'`.
  - `python, ###` (no letters or digits) → `ValidationError` naming `SCRAPE_TERMS` with `no letters or digits`.
  - `python, python` (the exact same term) → valid, both entries kept.
- **UT-023** (error): `SCRAPE_MAX_PAGES=abc` → `ValidationError` naming `SCRAPE_MAX_PAGES`; `SCRAPE_MAX_PAGES=0` → error.
- **UT-024** (error): `SCRAPE_DOWNLOAD_DELAY=0.5` → `ValidationError` naming `SCRAPE_DOWNLOAD_DELAY`.
- **UT-025** (error): `SCRAPE_CRON="61 * * * *"` → `ValidationError` naming `SCRAPE_CRON`.
- **UT-026** (error): `SCRAPE_TIMEZONE="Mars/Olympus"` → `ValidationError` naming `SCRAPE_TIMEZONE`.
- **UT-027** (boundary): `SCRAPE_RUN_TIMEOUT_MINUTES=19` → `ValidationError` naming the key; `=20` → valid.

### Parsers (Spec: Integration Points › field mapping)

- **UT-030** (happy): `vagas.parse_listing(vagas_python_p1.html, "https://www.vagas.com.br/vagas-de-python")` → 40 jobs. The first job equals the values recorded from the fixture at capture time. Shape: `source="vagas"`, numeric `external_id`, non-empty `title`, `url` starting with `https://www.vagas.com.br/vagas/v`, `company` without surrounding whitespace, `description` without `<mark>` tags, `published_label` like `09/10/2026`.
- **UT-031** (happy): the same page → `next_url == "https://www.vagas.com.br/vagas-de-python?pagina=2&q=python"`. Parsing the same fixture with `page_url="http://127.0.0.1:9999/vagas-de-python"` → `next_url == "http://127.0.0.1:9999/vagas-de-python?pagina=2&q=python"`, and every job `url` starts with `http://127.0.0.1:9999/` (URL resolution, review round 2 issue 010).
- **UT-032** (boundary): `vagas_python_p2_xhr.html` (the last page, an XHR response) → more than 0 jobs and `next_url is None`.
- **UT-033** (boundary): a vagas card without `data-id-vaga` is skipped; a card without `span.emprVaga` yields `company=None`.
- **UT-034** (happy): `infojobs.parse_listing(infojobs_python_p1.html, …)` → 20 jobs. The first is `external_id="11911899"`, `title="Desenvolvedor Python"`, `company="ISLA"`, `location="Porto Alegre - RS"`, `published_label="28 out"`, `url="https://www.infojobs.com.br/vaga-de-desenvolvedor-python-em-rio-grande-do-sul__11911899.aspx"`, or the equivalent recorded values if task 3 captures a newer page.
- **UT-035** (boundary): an Infojobs card without `h2.js_vacancyTitle` is skipped.
- **UT-036** (boundary): both parsers on `empty_listing.html` → `jobs == ()` and `next_url is None`.
- **UT-037** (happy): `vagas.parse_listing(vagas_programador_p2_xhr.html, "https://www.vagas.com.br/vagas-de-programador?pagina=2&q=programador")` → more than 0 jobs, and `next_url` is the absolute URL of page 3 (`…pagina=3…`).
- **UT-038** (boundary): sanitization (rule 27), on synthetic cards:
  - a title containing `\x00` is stored without it;
  - a card whose id has 65 characters is skipped;
  - a card whose id has 64 characters is kept.
- **UT-039** (error): the off-origin guard (`_spec.md` › Integration Points). The vagas spider, built with `base_url="http://127.0.0.1:9999"`, parses a page whose `#maisVagas@data-url` is the absolute `https://www.vagas.com.br/vagas-de-python?pagina=2` → no request is issued; the term records `error` starting with `parse error: OffOriginURLError:`; jobs from that page are kept. The spider's `allowed_domains == ["127.0.0.1"]`.

### Spiders (Spec: ADR-003, Business Rules 16–17)

- **UT-040** (happy): `slugify_term`, parametrized: `"desenvolvedor python"`→`"desenvolvedor-python"`, `"desenvolvedor .net"`→`"desenvolvedor-net"`, `"engenheiro de software"`→`"engenheiro-de-software"`.
- **UT-041** (happy): the spiders' `start_requests` with `terms=["desenvolvedor python", "programador"]` → vagas: `https://www.vagas.com.br/vagas-de-desenvolvedor-python`, `…/vagas-de-programador`; Infojobs: `https://www.infojobs.com.br/vagas-de-emprego-desenvolvedor-python.aspx?page=1`, `…programador.aspx?page=1`. Each request carries `meta["term"]`.
- **UT-042** (happy): the vagas spider parsing `vagas_python_p1.html` for term T yields 40 jobs and one follow-up request to the `next_url`, with header `X-Requested-With: XMLHttpRequest` and `meta["term"] == T`. Parsing `vagas_python_p2_xhr.html` yields jobs and no follow-up.
- **UT-043** (state): the Infojobs spider walking page 1 (HTML), the page 2 and 3 fragment fixtures and the end-of-list fragment for term T: each of the first three yields 20 unseen jobs and a request for the next page (the list-fragment URL, not `?page=N` HTML); the end-of-list page yields 0 jobs and no request; `pages == 4`. A page that only repeats earlier ids also ends the walk (`pages == 2`).
- **UT-044** (boundary): with `max_pages=1`, parsing page 1 yields no follow-up request; with `max_pages=20`, parsing page 20 yields none.
- **UT-045** (error): the errback for term A with a 403 `HttpError` records `error == "HTTP 403 Forbidden"` for A; term B's state is untouched.
- **UT-046** (state): ids seen for term A do not count as seen for term B (parsing the same fixture for B yields 20 jobs and a next request).
- **UT-047** (error): the errback with `IgnoreRequest` raised by `RobotsTxtMiddleware` records `error == "blocked by robots.txt"`.
- **UT-048** (happy): `build_scrapy_settings(settings)` with defaults → `ROBOTSTXT_OBEY=True`, `CONCURRENT_REQUESTS_PER_DOMAIN=1`, `DOWNLOAD_DELAY=1.0`, `RANDOMIZE_DOWNLOAD_DELAY=False`, `AUTOTHROTTLE_ENABLED=False`, `TWISTED_REACTOR=None`, `DOWNLOAD_TIMEOUT=30`, `CLOSESPIDER_TIMEOUT=3000` (60 − 10 minutes), `USER_AGENT` equal to `SCRAPE_USER_AGENT`, `ITEM_PIPELINES` empty.
- **UT-049** (error): the spider's `spider_error` handler, given an `AttributeError("x")` raised while parsing a response with `meta["term"] == "A"`:
  - records `error == "parse error: AttributeError: x"` for A;
  - leaves A's jobs from earlier pages in place;
  - issues no further request for A;
  - leaves term B untouched (rule 28).

### Application services (Spec: Core Interfaces › `services.py`)

- **UT-050** (happy): `JobQueryService.search(JobQuery())` with `FixedClock(2026-10-30T12:00Z)` and `inactive_after=7d` → the repository receives `active_since == 2026-10-23T12:00Z`, `page=1`, `size=20`. Parametrized with `inactive_after=3d` → `2026-10-27T12:00Z`.
- **UT-051** (happy): `JobQuery(include_inactive=True)` → `active_since is None`.
- **UT-052** (error): `JobQuery(seen_from=2026-10-20, seen_to=2026-10-01)` → `InvalidPeriodError`.
- **UT-053** (boundary): tz `America/Sao_Paulo`, `seen_from=2026-10-01`, `seen_to=2026-10-15` → criteria `seen_from == 2026-10-01T03:00:00Z`, `seen_to == 2026-10-16T02:59:59.999999Z`.
- **UT-054** (boundary): `JobQuery(q="   ", location="")` → criteria `text is None`, `location is None`.
- **UT-055** (state): `get(999)` on an empty fake → `JobNotFoundError(999)`; `get(id)` for a job last seen 10 days ago → a `JobView` with `active is False`.
- **UT-056** (happy): `CollectionService.start_run(MANUAL, expected_combinations=24)` with no active run → returns the new id; the fake has one `running` run with trigger `manual` and `expected_combinations == 24`.
- **UT-057** (state): an active run started 5 minutes ago, `run_timeout=60m` → `RunAlreadyActiveError(run_id, started_at)`; no new run.
- **UT-058** (state): an active run started 61 minutes ago, `run_timeout=60m` → that run becomes `failed` with error `interrupted`, then a new run is created.
- **UT-059** (happy): `complete_run` with outcomes `vagas/desenvolvedor python` (jobs "Desenvolvedor Python Sênior" and "Analista de Suporte") and `infojobs/desenvolvedor python` (job "Dev Pleno") → upsert is called for 2 jobs with seniorities `senior` and `mid`. Results: vagas `new=1, discarded=1`; infojobs `new=1`. Status `success`, `finished_at` = clock now, and there is one result per outcome.
- **UT-060** (idempotency): the same `ScrapedJob` (same source and external_id) in outcomes `vagas/desenvolvedor` and `vagas/programador` → first `new=1`, second `seen_again=1`.
- **UT-061** (state): outcome A succeeds with 2 jobs; outcome B has `error="HTTP 403 Forbidden"`, `pages=3` and 1 job collected before the failure → B's job is upserted; B's result is `status=failed, pages=3, new=1, error="HTTP 403 Forbidden"`; run `partial`.
- **UT-062** (state): every outcome has an error → run `failed`.
- **UT-063** (error): `fail_run(run_id, "crawler crashed: …")` → run `failed`, `error` set, `results == ()`.
- **UT-064** (state): a stored job (fake) whose new title "Programador de CNC" is irrelevant → no upsert; it counts as `discarded`, and the stored `last_seen_at` is unchanged.
- **UT-065** (error): `CollectionRunQueryService.get(404)` → `CollectionRunNotFoundError(404)`.
- **UT-066** (state): `complete_run` when the fake repository's `finish` raises `RunTakenOverError` → the error propagates, and the fake UoW rolled back (no upserts kept).
- **UT-067** (happy): `CollectionService.startup_reason()` over a fake `UnitOfWork` whose `probe.is_empty()` and `runs.latest_finished()` are set by the test, with a `FixedClock` → returns what `startup_collection_reason` returns for the same inputs. Two cases: an empty store gives `"empty_job_store"`; a non-empty store whose latest run is 25 h old gives `"no_recent_run"`. `CollectionService.ping()` calls `uow.probe.ping()` once and propagates its error.
- **UT-068** (ordering): the real `CollectionService.complete_run` over the fake `UnitOfWork`, which records an event log, with a recording `before_commit` (review round 6, issue 001).
  - The log is: every `upsert`, then `runs.finish`, then `before_commit` (exactly once), then the UoW's `__aexit__` commit.
  - When the fake `runs.finish` raises `RunTakenOverError`, `before_commit` is **not** called, and the UoW rolls back.
  - Without `before_commit` (`None`), `complete_run` behaves the same and does not raise.

### CLI `collect` (Spec: `_dx.md` › CLI)

CLI cases call `main([...], deps=CliDeps(...))`, with a fake scraper and an `open_collection_service` that yields a service over in-memory fakes. There are two exceptions:
- UT-073 calls `main([...])` with `deps=None` and environment variables, because it tests configuration loading.
- UT-077 tests `build_cli_deps` directly.

- **UT-070** (happy): `main(["collect"])` with a fake service and scraper (2 outcomes, both successful) → stdout starts with `Collection run 1 started (trigger: manual)`, has one line per outcome and ends with `Collection run 1 finished: success in …`; exit `0`.
- **UT-071** (state): final status `partial` → exit `0`; `failed` → exit `1`.
- **UT-072** (error): `start_run` raises `RunAlreadyActiveError(7, 2026-10-30T09:00Z)` → stderr `Another collection run (id 7) is in progress since 2026-10-30T09:00:00Z.`; exit `3`; the scraper is not called.
- **UT-073** (error): env `SCRAPE_TERMS=""` → stderr starts with `Invalid configuration: SCRAPE_TERMS:`; exit `2`. Also env `SCRAPE_TERMS="python,Python"` (a slug collision, review round 7, issue 002) → the same prefix, stderr names `'python', 'Python'`; exit `2`.
- **UT-074** (happy): `main(["collect", "--json"])` → stdout is exactly one JSON document that validates against `RunDetailOut`; exit `0`.
- **UT-075** (error): the scraper raises `ScrapeCrashedError("boom")` → `fail_run` is called with a message containing `boom`; stderr `Collection run 1 failed: boom`; exit `1`.
- **UT-076** (error): `start_run` raises a connection error → stderr `Cannot connect to the database at db:5432.`; exit `1`.
- **UT-077** (happy): `build_cli_deps(Settings(relevance_include_keywords="golang", scrape_terms="desenvolvedor go"))`:
  - `deps.relevance.is_relevant("Desenvolvedor Golang")` is `True`;
  - `deps.relevance.is_relevant("Desenvolvedor Python")` is `False`;
  - `deps.settings.scrape_terms == ["desenvolvedor go"]`.

  With that `deps` and `scraper` replaced by a recording fake (`dataclasses.replace`), `main(["collect"], deps=…)` calls `scrape(["desenvolvedor go"])`.
- **UT-078** (happy): `main(["collect", "--trigger", "startup"])` records trigger `startup`; `--trigger bogus` → argparse error, exit `2`.
- **UT-079** (error): `complete_run` raises `IntegrityError` → `fail_run` is called with `ingest failed: IntegrityError: …` through a **new** `open_collection_service()` context; stderr `Collection run 1 failed: ingest failed: IntegrityError: …`; exit `1` (rule 26).
- **UT-104** (state): the scraper raises `ScrapeInterruptedError` → `fail_run(run_id, "interrupted by signal")`; stderr `Collection run 1 interrupted by signal.`; exit `4` (rule 24).
- **UT-105** (state): `complete_run` raises `RunTakenOverError(1)` → `fail_run` is **not** called; stderr `Collection run 1 was taken over by another process; its results were discarded.`; exit `1`.
- **UT-117** (state): signal handling across phases (review round 3, reopened issue 003). The fake scraper's `scrape()` runs these steps:
  1. It asserts that `signal.getsignal(SIGTERM)` and `signal.getsignal(SIGINT)` are still the collector's handler, after `start_run`'s `asyncio.run` has completed.
  2. It invokes that handler with `SIGTERM`.
  3. It returns a valid report.

  Expected:
  - `complete_run` is never called;
  - `fail_run(run_id, "interrupted by signal")` is called;
  - exit `4`;
  - after `main` returns, the original handlers are restored.

  Further cases:
  - **During ingestion, before commit:** invoking the handler from inside the fake `complete_run` while it awaits, with `cancellable` set → the task is cancelled. The re-read (`get_run` on the fake service) shows the run `running`, so `fail_run` is called and exit is `4`.
  - **During `start_run`** (review round 4, issue 001): the handler is invoked inside the fake `start_run` after it has created run 1 → `start_run` is **not** cancelled and returns `1`. Then `scrape` is never called, `fail_run(1, "interrupted by signal")` is called, exit is `4`, and the fake repository has no `running` run left.
  - **After commit:** the fake `complete_run` marks run 1 `success`, calls the `before_commit` hook it received (the CLI's `phase.clear_cancellable`), and then the handler is invoked before the phase returns → no cancellation and no `fail_run`. No "taken over" message is printed, `signal_after_finish` is logged, and exit is `0`. The test also asserts that `complete_run` received a non-`None` `before_commit`.
  - **Signal during a terminal `fail_run`** (review round 5, issue 002): the scraper raises `ScrapeCrashedError("boom")`, and the handler is invoked inside the fake `fail_run` → `fail_run` is called exactly once, with the crash message; stderr `Collection run 1 failed: boom`; `signal_after_finish` is logged; exit `1`; no `RunTakenOverError`.
  - **Cancellation landing after commit:** a fake `complete_run` marks the run `success` and then raises `CancelledError` → the re-read (`get_run` on the fake service) shows `success`, so exit is `0` with `signal_after_finish`, never the "taken over" message or exit `1`.

### Scheduler (Spec: ADR-004)

The scheduler cases call the seams in `take_jobs.cli.scheduler` (`_spec.md` › Core Interfaces): `wait_for_database`, `run_startup`, `configure_scheduler`, `make_shutdown_handler` and `run_scheduler`. They use a `CliDeps` whose `clock` is a `FixedClock`, `sleep` records the delays, `runner` records calls, and `scheduler_factory` returns an APScheduler `BackgroundScheduler` that is never started (or a stub whose `start()` returns at once). No case blocks.

- **UT-080** (happy): `SCRAPE_ON_START=true`, parametrized:
  - an empty store → the runner is called once with trigger `startup` before the scheduler loop starts, and event `startup_collection reason=empty_job_store` is logged;
  - a non-empty store whose latest finished run started 25 h ago → the same, with `reason=no_recent_run`.
- **UT-081** (happy): the store has jobs and the latest finished run started 3 h ago → the runner is not called at startup, and event `startup_collection_skipped reason=recent_run_exists` is logged.
- **UT-082** (happy): `SCRAPE_ON_START=false` with an empty store → the runner is not called.
- **UT-083** (happy): after setup, the scheduler has exactly one job: `CronTrigger` hour 6, minute 0, tz `America/Sao_Paulo` (and hour 22, minute 30 for `SCRAPE_CRON="30 22 * * *"`; Sundays only for `"0 6 * * 0"`), `max_instances=1`, `coalesce=True`, `misfire_grace_time=3600`, calling the runner with trigger `scheduled`. No other job exists, so there is no retry path.
- **UT-084** (happy), `SubprocessCollectionRunner`, with `subprocess.Popen` patched:
  - `run(RunTrigger.SCHEDULED)` starts `Popen` with argv `[sys.executable, "-m", "take_jobs", "collect", "--trigger", "scheduled"]` and `shell=False`. It sets `current` while waiting, returns the child's exit code, clears `current` afterwards, and logs the exit code.
  - `run()` waits by polling `poll()`; it never calls `wait()`, which the patched `Popen` asserts.
  - `terminate_current(25)` while `current` is set → `current.terminate()`, then polling `poll()` until it returns a code, and `kill()` only when 25 s pass without one.
  - `terminate_current` while idle → no-op.
- **UT-085** (error): `wait_for_database(open_service, sleep=…)`, where `open_service` yields a fake `CollectionService` whose `ping()` raises a connection error 3 times and then succeeds → returns after `sleep` recorded `[1, 2, 4]`, and `startup_probe_failed` is logged 3 times. When `ping()` always fails → `DatabaseUnavailableError` once the recorded delays sum to at least 60, and `run_scheduler(deps)` returns `1`.
- **UT-086** (happy): `subprocess.run([sys.executable, "-m", "take_jobs", "--help"])` → exit `0`, and the output lists `collect` and `scheduler` (`__main__.py` exists).
- **UT-087** (state): `make_shutdown_handler(scheduler, runner)` with a recording fake runner; the handler is invoked with `SIGTERM`:
  - **scheduler running:** `scheduler.shutdown(wait=False)` is called, `runner.terminate_current(25)` is called, and the handler raises `SystemExit(0)`;
  - **scheduler not yet started:** `shutdown` is not called; the other effects are the same.
- **UT-089** (boundary): a stop during the startup run returns as soon as the collector exits (review round 4, issue 002). No `Popen` patch is used.
  - **Setup:**
    - A real `SubprocessCollectionRunner` runs a short-lived child, a top-level helper script that handles SIGTERM by sleeping 1 s and exiting `4`, in the **main** thread.
    - The handler is installed with `make_shutdown_handler(stub_scheduler, runner, wait_s=25)`.
    - A timer sends `os.kill(os.getpid(), SIGTERM)` 1 s into the run.
  - **Expected:**
    - the handler raises `SystemExit(0)` within 3 s of the signal;
    - `kill()` was not called;
    - the child's exit code is `4`.
- **UT-088** (ordering): `run_scheduler(deps)` installs the shutdown handler **before** the startup run (review round 3, reopened issue 003).
  - **Setup:** `signal.signal` is patched to record installations. The fake runner's `run()` records the call order, then invokes the currently installed SIGTERM handler, simulating `docker compose down` during the startup collection.
  - **Expected:**
    - the handler was installed before `wait_for_database` and before `runner.run`;
    - `runner.terminate_current(25)` is called;
    - `run_scheduler` ends with `SystemExit(0)`;
    - the log order is `scheduler_started`, then `startup_collection`.

### API (Spec: API Endpoints; `_dx.md` › HTTP API, Errors)

Each case uses `create_app()` with dependency overrides for the services and the probe.

- **UT-090** (happy): `GET /jobs` → `200`; the body has keys `items, total, page, size, pages`; the service received `page=1, size=20, include_inactive=False`.
- **UT-091** (error): parametrized `GET /jobs?size=0`, `?size=101`, `?page=0`, `?seen_from=31/10/2026` → `422`, `error.code == "validation_error"`, with `details[0].field` equal to `size`, `size`, `page` and `seen_from` respectively.
- **UT-092** (error): the service raises `InvalidPeriodError` → `422`, `error.code == "invalid_period"`, message `seen_from (2026-10-20) must be on or before seen_to (2026-10-01).`.
- **UT-093** (error): `GET /jobs?source=linkedin` → `422 validation_error`, field `source`.
- **UT-094** (error): `GET /jobs?seniority=lead` → `422 validation_error`, field `seniority`.
- **UT-095** (error): `GET /jobs?q=` + 101 × `"a"` → `422 validation_error`, field `q`.
- **UT-096** (error): `GET /jobs/999999` with the service raising `JobNotFoundError` → `404`, body `{"error": {"code": "job_not_found", "message": "Job 999999 was not found.", "details": []}}`; `GET /jobs/abc` → `422`, field `job_id`.
- **UT-097** (error): `GET /collection-runs/404` → `404`, `collection_run_not_found`, message `Collection run 404 was not found.`.
- **UT-098** (error): `GET /nope` → `404`, `error.code == "not_found"`.
- **UT-099** (error): the service raises `sqlalchemy.exc.OperationalError` → `503`, `database_unavailable`, message `The database is unavailable. Try again later.`.
- **UT-100** (error): the service raises `RuntimeError("secret detail")` → `500`, `internal_error`; the body does not contain `secret detail`; event `api_unhandled_error` is logged.
- **UT-101** (happy/error): `GET /health` with a probe that pings OK → `200 {"status": "ok", "database": "ok"}`; with a probe that raises → `503 {"status": "unavailable", "database": "unreachable"}`; with a probe that sleeps 5 s → `503` in under 3.5 s.
- **UT-102** (happy): `GET /openapi.json` lists exactly the paths `/jobs`, `/jobs/{job_id}`, `/collection-runs`, `/collection-runs/{run_id}` and `/health`, each with its documented error responses. With an app created from a registry containing an extra source `fakeboard`, the `source` parameter's enum is `["fakeboard", "infojobs", "vagas"]`. `GET /docs` → `200` HTML.
- **UT-103** (happy): `GET /jobs?source=vagas&source=infojobs&seniority=senior&seniority=mid&location=Sao%20Paulo` → the service receives `sources={"vagas","infojobs"}`, `seniorities={senior, mid}` and `location="Sao Paulo"`.

### Scraper child process (Spec: ADR-002; rules 24–25)

- **UT-106** (state): the close-reason mapping in the child, given spider state with term A finished and term B not finished, and reason `closespider_timeout` → A keeps its recorded outcome; B gets `error == "run time limit reached"`, with its pages and jobs so far kept.
- **UT-119** (state): the `finished` close reason never reads as success (review round 7, issue 002; `_spec.md` › Scraper child).
  - Given spider state with term A that never ran and term B walked but not finished, and reason `finished` → both get `error == "crawl closed: finished before the term completed"`; B keeps its pages and jobs so far.
  - Terms that recorded an outcome keep it under `finished`: an HTTP error stays `HTTP 403 Forbidden`, a success stays `None`.
  - Real crawl, fixture server: an Infojobs fragment that redirects to an already fetched URL (dropped by the duplicate filter) → the Infojobs term fails with that message, keeps page 1's 20 jobs, and Vagas is unaffected.
  - Real crawl with `terms=("python", "Python")` (same slug, bypassing `Settings`) → the first term succeeds on both sources; the second has 0 pages and the same error.
- **UT-107** (state): interruption is decided by the parent.
  - **Setup:** the child target is replaced by a top-level function that installs nothing, sleeps 60 s, then sends a valid report. `scrape()` runs in a thread, and the test calls `scraper.interrupt()` after 1 s.
  - **Expected:** `scrape()` raises `ScrapeInterruptedError` within 7 s, the child is no longer alive, and its exit code is negative (killed).
  - **Also:** the close-reason mapping with reason `None` or `shutdown` → every unfinished term gets `crawl closed: <reason>`, never success.
  - **Interrupt before the child exists** (review round 4, issue 001): `scraper.interrupt()` is called before `scrape()`, then `scrape()` is called → `ScrapeInterruptedError` within 7 s, and no crawl child is left alive. If a child was started, it is terminated right after `process.start()`.
- **UT-108** (error): `ScrapyJobScraper.scrape` with the child target replaced by a top-level function that exits with code 1 without sending a report → `ScrapeCrashedError` whose message names the exit code. It must not hang: the call is wrapped in a 10-second timeout, which needs the parent to close its copy of the child's end of the pipe.
- **UT-109** (boundary): a large report crosses the real spawn boundary without deadlock (review round 2, issue 001). The child target is replaced by a top-level function that sends a `ScrapeReport` of 15,000 synthetic `ScrapedJob`s (more than 1 MiB pickled), then exits `0`. `scrape()` returns that report, equal in length and content, within 30 s, on Linux and macOS.
- **UT-116** (error): the network guard stops a **Scrapy** request in the crawl child (FR-30; review round 3, reopened issue 010).
  - **Setup:**
    - A local HTTP server listens on `127.0.0.1` and counts hits.
    - A real `ScrapyJobScraper`, built with `child_initializer=functools.partial(install_test_socket_guard, allow_hosts=["::1"])` and sources `with_base_url(SOURCES, "http://127.0.0.1:<port>")`, runs `scrape(["python"])`. The address `127.0.0.1` is not on that allow list.
  - **Expected:**
    - every outcome has an `error` starting with `SocketConnectBlockedError: ` (the generic `<ExceptionType>: <message>` errback format, `_spec.md` › Integration Points; review round 4 issue 003);
    - the server records **0** hits.
  - **Control case:** with the default `install_test_socket_guard` (which allows loopback), the same scrape reaches the server, with at least 1 hit.

  This proves the guard covers Twisted's `connect_ex` path, not only `socket.connect`.

### Static repository contracts (Spec: Testing Approach; PRD O1)

These read files from the repository; none needs the network or Docker.

- **UT-110** (happy): `docker-compose.yml` (FR-27, issue 011):
  - services `db`, `migrate`, `api` and `scheduler` exist;
  - `db` has a `pg_isready` healthcheck and no `ports`;
  - `migrate.depends_on.db.condition == "service_healthy"`;
  - `api` and `scheduler` have `depends_on.migrate.condition == "service_completed_successfully"`;
  - `api` and `scheduler` have `restart: unless-stopped`;
  - `scheduler` has `init: true` and `stop_grace_period: 30s`;
  - no service has `env_file`;
  - the raw `db` healthcheck is `["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]`. When `docker compose config` is available, it renders with no "variable is not set" warning and with non-empty `-U`/`-d` arguments after the container's shell expansion (review round 2 issue 003).
- **UT-111** (happy): `.github/workflows/ci.yml` (FR-29):
  - triggers include `push` and `pull_request`;
  - checkout uses `fetch-depth: 0`;
  - steps run `uv sync --frozen`, `ruff format --check`, `ruff check`, `lint-imports`, and `pytest` with `--cov-fail-under=80`.
- **UT-112** (happy): `README.md` (FR-31) has the headings for overview, running, querying the API, configuration and "v1 → v2", the CI badge, and the O5 query from `_spec.md` › Monitoring.
- **UT-113** (happy): `git rev-parse v1^{commit}` starts with `52018b3` (FR-32). The test is skipped, with reason `tag v1 not present`, only when the tag is absent; MAN-005 then owns it.
- **UT-114** (happy): `docs/tasks/fastapi-refactor/` contains `_prd.md`, `_spec.md`, `_user_stories.md`, `_dx.md`, `_tests.md`, `_tasks.md`, `adrs/`, at least one `reviews-*/` and `memory/` (FR-33).
- **UT-115** (error): with the session's socket guard, opening a TCP connection to `93.184.216.34:80` raises `pytest_socket.SocketConnectBlockedError` (FR-30). This is the class raised under `--allow-hosts` (review round 2 issue 010).

## Integration Tests

Real PostgreSQL 17 via testcontainers, with migrations applied.

### Persistence

- **IT-001**: Alembic — on an empty database, `upgrade head` creates `jobs`, `collection_runs`, `collection_run_results`, the extensions `unaccent` and `pg_trgm`, the function `immutable_unaccent`, and every index named in `_spec.md` › Data Models. `downgrade base` removes the tables, and a new `upgrade head` succeeds.
- **IT-002**: `SqlAlchemyJobRepository.upsert`:
  - A new `ScrapedJob` at `t1` → returns `True`; the row has every field, `first_seen_at == last_seen_at == t1`, and `company is None` when it was absent.
  - The same identity with a new title at `t2` → returns `False`; one row; `last_seen_at == t2`, `first_seen_at == t1`, the title is updated.
  - The same `external_id` with `source="infojobs"` → a second row.
- **IT-003**: text search on seeded jobs:
  - `q="python"` matches the title "Desenvolvedor Python".
  - `q="bom futuro"` matches the company "Bom Futuro".
  - `q="MIGRACAO"` matches the description "migração de ETLs".
  - `q="50%"` matches only the description containing the literal "50%", and `q="a_b"` only the literal "a_b".
  - `q="kotlin"` → `total == 0` and `items == ()`.
  - A job with only a title ("Desenvolvedor Rust", `company = NULL`, `description = NULL`) is found by `q="rust"` (issue 013).
- **IT-004**: filters on a seeded table of 8 jobs with known source, location, seniority and seen dates, parametrized:
  - `sources={"infojobs"}` and the OR of both sources.
  - `location="sao paulo"` matching "São Paulo - SP".
  - `seniorities={senior, mid}`.
  - The overlapping period of US-012.AC-4: a job seen from 09-25 to 10-02 matches 10-01…10-15; one seen from 10-16 to 10-20 does not.
  - `active_since` excludes a job last seen 8 days ago, and `None` includes it.
  - The combined period + active case of US-012.EC-4.

  Each case asserts the exact set of ids returned.
- **IT-005**: ordering and pagination:
  - 45 jobs with deliberate ties in `last_seen_at` and `first_seen_at` → order `last_seen_at desc, first_seen_at desc, id desc`.
  - `page=2, size=20` returns positions 21–40.
  - `page=3` returns 5; `page=4` returns `items == ()` with `total == 45`.
- **IT-006**: `SqlAlchemyCollectionRunRepository`:
  - `start` → `running`; a second `start` → `RunAlreadyActiveError` carrying the first run's id (the DB guard).
  - `finish` with 2 results → `get` returns them; `finish` again → raises (0 rows).
  - `list(page=1, size=20)` orders by `started_at desc`.
  - A running run → `get` returns `results == ()` and `finished_at is None`.
  - An empty table → `list` returns `total == 0`.
  - A finished run with results `(new 3, seen 1, disc 2)` and `(new 0, seen 4, disc 1)` → `list()` returns it with `totals == RunTotals(3, 5, 3)` and `results == ()`; `get()` returns the same totals plus both results (issue 005).
  - `latest_finished()` ignores a `running` run and returns the most recently started finished one.
- **IT-010**: `SqlAlchemyJobStoreProbe`:
  - `is_empty()` → `True` on an empty table and `False` after one upsert.
  - `ping()` succeeds.
  - With a DSN pointing at a closed port, `ping()` raises within 3 s.

### Collection flow

- **IT-007**: one pytest process. The fixture HTTP server serves `vagas_python_p1.html`, `vagas_python_p2_xhr.html` (served for the follow-up URL), `infojobs_python_p1.html` and the three Infojobs fragment fixtures (pages 2-4). The registry is `with_base_url(SOURCES, server_url)`, and `terms=["python"]`. Steps: `asyncio.run(start_run)` → `ScrapyJobScraper.scrape(["python"])` → `asyncio.run(complete_run)`, performed **twice** in the same process. Expected:
  - Neither cycle raises: no `ReactorNotRestartable`, no pickling error; this covers R1 and R6.
  - Each report has 2 outcomes, one per source.
  - The vagas outcome has `pages == 2`; the Infojobs outcome has `pages == 4` and 60 jobs (the walk goes past page 2).
  - Both runs finish as `success`, and the database holds the relevant jobs from both sources.
- **IT-008**: `CollectionService.complete_run` with the real database and a canned report of 3 jobs, where `runs.finish` is patched to raise `RuntimeError("db gone")` after the upserts. Then `fail_run` is called as the CLI does (rule 26). Expected:
  - no rows in `jobs` and none in `collection_run_results`;
  - the run is `failed` with `error == "ingest failed: RuntimeError: db gone"`.

  This covers Safety Invariant 3.
- **IT-009**: CLI `collect` against the real database with a fake scraper:
  - A `running` row started 5 minutes ago → exit `3`, and still only 1 run exists.
  - A `running` row started 61 minutes ago (`SCRAPE_RUN_TIMEOUT_MINUTES=60`) → that row becomes `failed` with error `interrupted`, the new run finishes `success`, and the exit code is `0`.
- **IT-013**: signals during a run. In every variant, a helper process (`spawn`, its own process group via `os.setpgid(0, 0)`) calls `main(["collect"], deps=…)` against the real database. Its scraper uses `with_base_url(SOURCES, server_url)` and `child_initializer=install_test_socket_guard`. Parametrized:
  - **(a) SIGTERM during the crawl.** The fixture server holds every listing response for 25 s. After the server receives the first listing request, the test sends SIGTERM to the helper.
  - **(b) Ctrl+C.** Same server behavior. The test sends SIGINT to the helper's whole process group (`os.killpg`), as a terminal would.
  - **(c) SIGTERM during ingestion.** The scraper serves fixtures without delay. The helper's `open_collection_service` wraps the repository so that `upsert` sleeps 2 s per job. The test sends SIGTERM once the first `upsert` has started (signalled through a pipe).

  Expected, in every variant:
  - the helper exits with code `4` within **12 s** of the signal, well inside the scheduler's 25-second wait;
  - no crawl child process is left alive;
  - exactly one run exists, `failed`, with `error == "interrupted by signal"`;
  - `jobs` is empty, so in (c) the partial ingestion was rolled back;
  - a following `main(["collect"])` is not refused with code `3`.

  Covers: rule 24, Safety Invariant 8, US-003.EC-5, US-004.EC-2 (review round 2, reopened issue 003).
- **IT-014**: the O5 query from `_spec.md` › Monitoring, over the 7 complete days ending yesterday in `America/Sao_Paulo`, with `:expected = 24`. Days are counted back from today, D-1 to D-7. Parametrized:
  - **(a)** D-1 to D-5 each have one finished run, with `expected_combinations = 24` and 24 `success` results. D-6 has a `failed` run (crash) with `expected_combinations = 24` and no results. D-7 has no run. Expected `71.4`, that is 120 / 168 (issue 009).
  - **(b)** D-1 to D-7 all have 24/24 `success`, and **today** has no finished run, or has a run still `running`. Expected `100.0`: today is outside the window (review round 2, issue 002).

### Performance and configuration

- **IT-011** (`perf`): seed 50,000 jobs with realistic text (generated titles, companies, 300-character descriptions) via `COPY`, then `ANALYZE`. Run 50 searches through `JobQueryService` mixing `q` (≥ 3 characters), `location`, `source`, `seniority`, the default active filter and `size=20`. Then run a separate set of 20 searches with 1- and 2-character `q` values (`go`, `js`, `ui`, `c`). Expected:
  - p95 latency < 300 ms for each set (O7);
  - `EXPLAIN` for a ≥ 3-character `q` search shows `ix_jobs_search_text_trgm` in use.

  If the short-query set misses the target, the implementer records the numbers and returns to the user (ADR-005 Risks); the target is not silently lowered.
- **IT-012**: static configuration contract:
  - The set of keys in `.env.example` equals the set of `Settings` fields (env names) plus `API_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`.
  - Every key appears in `docker-compose.yml` as `${KEY-default}` (no colon), with a default equal to `.env.example`, and no `${KEY:-…}` form exists (issue 012).
  - With `.env` containing `RELEVANCE_EXCLUDE_KEYWORDS=`, `docker compose config` renders that variable as empty for `scheduler`. This case is skipped when the `docker` CLI is absent.
  - The `db` service has no `ports:`.
  - `.env` is listed in `.gitignore`.
  - **Secret scan** (issue 014, scope fixed in review round 2):
    - **Scanned files:** every file from `git ls-files`, plus `.env.example`, except:
      - `docs/**/*.md`, because these documents describe the scan's own patterns. The never-quote policy (`_spec.md` › User Experience › Credentials) still applies to them and is checked at review.
      - The scan's own module, `tests/static/test_secret_scan.py`, and its fixtures, `tests/fixtures/secrets/`.
    - **Patterns:** `(?i)(password|passwd|pwd|secret|token)\s*[:=]\s*["']?([^\s"'#,]+)` and `://[^:/\s@]+:([^@\s]+)@`.
    - **Allowed captured values:** `take_jobs_dev`; `${…}` interpolations; `<…>` placeholders; the literal words `change-me` and `null`.
    - **Expected:** any other captured value fails the test, which reports the file and line but never prints the value.
    - **Self-check cases:** the scan passes on the current tree. It fails on the fixture `tests/fixtures/secrets/leak.env`, which contains `DATABASE_URL=postgresql://u:hunter2@h/db`, reporting `leak.env:1`. It passes on the fixture `ok.env`, which contains `POSTGRES_PASSWORD=take_jobs_dev`.

## End-to-End Tests

Each case is a **synchronous** test that goes through the public surfaces:
- `main([...], deps=build_cli_deps(settings, sources, child_initializer=install_test_socket_guard))`;
- `TestClient(create_app(settings, sources))`.

Both use the real composition and the real database. `sources = with_base_url(SOURCES, fixture_server_url)`, never the real sites. The crawl runs in its spawned child, so the repeated `collect` calls in E2E-002 and E2E-003 work in one session.

### Collect, then search (US-001, US-003, US-009, US-011, US-014, US-017, US-018)

- **E2E-001**: `main(["collect", "--json"])` with `SCRAPE_TERMS=python` → exit `0`; the JSON has `status == "success"` and 2 `results`. Then:
  - `GET /jobs?q=python` → `200`; every item has all `_dx.md` fields, `active == true`, and at least one item has `seniority` set.
  - `GET /jobs/{first id}` → `200`, the same object.
  - `GET /collection-runs` → 1 item whose `totals` equal the CLI JSON's.
  - `GET /collection-runs/{id}` → the same `results`.

### Relevance and deduplication (US-002, US-008)

- **E2E-002**: journey fixtures for terms `desenvolvedor` and `programador`. Both pages contain the job "Desenvolvedor Backend Java" with the same id; the `programador` page also contains "Programador de CNC".
  - After `collect`, `GET /jobs?q=cnc` → `total == 0`.
  - `GET /jobs?q=backend java` → `total == 1`.
  - The run detail shows `discarded == 1` for `programador` and `seen_again == 1` for the second combination that collected the Java job.
  - A second `collect` → the Java job keeps its `first_seen_at` and has a newer `last_seen_at`.

### Lifecycle (US-010)

- **E2E-003**: after `collect`, set one job's `last_seen_at` to 8 days ago directly in the database. Then:
  - `GET /jobs` does not contain it.
  - `GET /jobs?include_inactive=true` contains it with `active == false`.
  - `GET /jobs/{id}` → `active == false`.
  - Run `collect` again, with the fixture still listing it → `GET /jobs` contains it with `active == true`.

### Partial failure (US-005)

- **E2E-004**: the fixture server answers `403` for every Infojobs URL. `main(["collect"])` → exit `0`, and the summary line says `partial`. `GET /collection-runs/{id}`:
  - The Infojobs result has `status == "failed"` and `error == "HTTP 403 Forbidden"`.
  - The vagas result has `status == "success"`.
  - `GET /jobs?source=vagas` → `total > 0`.

### Health (US-016)

- **E2E-005**: `GET /health` on the app wired to the test database → `200 {"status":"ok","database":"ok"}`. On an app created with `DATABASE_URL` pointing at a closed port → `503 {"status":"unavailable","database":"unreachable"}`.

## Manual Checks

These cannot be automated without network access to the real sites, GitHub, or human judgment. Each is recorded with evidence in the task memory of the task that owns it.

- **MAN-001** (US-019, O4): from a fresh clone with no `.env`, run `docker compose up --build`. Record:
  - the time until `GET /health` returns `200`;
  - the time until `GET /jobs` returns real jobs (target ≤ 15 minutes);
  - the result of a second `docker compose up` within 24 h of the first run: data kept and the startup run skipped (`reason=recent_run_exists`). A run more than 24 h after the last finished run would instead collect with `reason=no_recent_run` (US-019.EC-3);
  - the result of setting `API_PORT=8001`.
- **MAN-002** (O5): after 7 days of operation, run the README's success-rate SQL query; the target is ≥ 95%. This is post-delivery, so it is recorded in the README and not gating the task graph.
- **MAN-003** (O6): sample 50 random stored jobs and record how many are genuinely development roles; the target is ≥ 90%. Done once after MAN-001.
- **MAN-004** (US-021): push the branch; the GitHub Actions run is green with all gates (format, lint, `lint-imports`, tests, coverage ≥ 80%), and the badge renders in the README.
- **MAN-005** (US-022): `git show v1 --no-patch` shows `52018b3`; the README has the five required sections; `docs/tasks/fastapi-refactor/` holds the PRD, the spec, the companions, the tasks, the reviews and the memory.
