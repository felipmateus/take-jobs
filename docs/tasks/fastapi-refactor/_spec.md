# Spec: take-jobs v2 — FastAPI refactor

- **Slug:** `fastapi-refactor`
- **Status:** Approved by the user on 2026-10-30
- **Date:** 2026-10-30
- **Source PRD:** [`_prd.md`](_prd.md) (FR-01–FR-33, objectives O1–O7)
- **Companions:** [`_user_stories.md`](_user_stories.md) · [`_dx.md`](_dx.md) · [`_tests.md`](_tests.md) · [`adrs/`](adrs/)

---

# Part I — Product

## Overview

- **Motivating Problem**: developer job openings are scattered across job boards with different searches and formats, and v1 of this project only scraped on demand, through an unsafe shell call, into a database with committed credentials. The simplest end-to-end behavior that solves it: **after one command, the system has collected developer jobs from a job board and an API returns them, searchable, as JSON.** Slice 1 delivers exactly that for vagas.com; later slices add Infojobs, relevance, lifecycle, run history and scheduling.
- **Who it is for**: primarily a technical evaluator assessing the author's portfolio; secondarily the author, as API consumer and maintainer (personas in [`_user_stories.md`](_user_stories.md#personas)).
- **Why it is valuable**: it turns scattered listings into one standardized developer job bank, refreshed daily. As a portfolio piece, it shows the move from an ad-hoc v1 to a spec-driven, layered, tested v2.

## Goals

After this ships:

- A consumer can search developer jobs from vagas.com and Infojobs in one place, by text, source, location, seniority and seen period, without visiting either site.
- The job bank refreshes itself daily, and immediately on the first start, with no manual step.
- Only software development jobs are stored. Each job appears once, knows when it was first and last seen, and stops being shown by default once it disappears from the sites.
- The maintainer can see, per run and per site × term, what was collected and what failed, without reading logs.
- An evaluator can start the whole system with one command, explore it through interactive docs, and trace every PRD requirement to tasks and tests.
- Scraping can no longer be triggered with arbitrary input, credentials can no longer leak through the repository, and a run can no longer loop forever on a site's pagination.

## User Stories

Canonical catalog: [Full user stories](_user_stories.md).

- US-001–US-007 — Collection: daily runs, deduplication, on-demand and initial runs, failure isolation, polite limits, extensible sources.
- US-008–US-009 — Relevance: developer-only filter and seniority.
- US-010 — Lifecycle: active and inactive jobs.
- US-011–US-015 — Search API: text search, filters, pagination, detail, interactive docs.
- US-016 — Operations: health check.
- US-017–US-018 — Run history: list and detail.
- US-019–US-022 — Developer experience: one-command startup, configuration, CI, visible evolution.

## Core Features

| Feature | What it does | PRD FRs | Stories |
| --- | --- | --- | --- |
| F1 Daily job collection | Collects every registered source × configured term on a daily schedule, on first start and on demand; stores each job once | FR-01–FR-10 | US-001–US-007 |
| F2 Relevance and seniority | Discards non-development titles; derives seniority from the title | FR-11–FR-13 | US-008, US-009 |
| F3 Job lifecycle | Hides jobs not seen for 7 days by default; keeps history; reactivates on reappearance | FR-14–FR-16, FR-19 | US-010 |
| F4 Job search API | Read-only JSON search, detail, docs and health | FR-17–FR-23 | US-011–US-016 |
| F5 Collection run history | Records every run and its per-combination outcome; exposes them via the API | FR-24–FR-26 | US-017, US-018 |
| F6 Developer experience and SDD evidence | One-command start, env configuration, CI, README, `v1` tag, versioned artifacts | FR-27–FR-33 | US-019–US-022 |

Interactions: F1 feeds F2 (every collected job passes through relevance and seniority before storage). F2 decides what F3 and F4 can ever see. F1 writes F5's records, and F3's "last seen" comes from F1. F6 packages the others.

## Business Rules

**Identity and deduplication**

1. A job is identified by its **source** plus the **site's own job identifier** (vagas.com `data-id-vaga`, Infojobs `data-id`). At most one stored job exists per identity.
2. Collecting an existing identity updates `last_seen_at` and the descriptive fields (title, company, location, description, publication label, URL, seniority) to the latest values. `first_seen_at` never changes.
3. Within one run, a job counted as `new` in one combination is counted as `seen_again` in any later combination that collects it again.

**Relevance** (applied to the title only)

4. Normalization for matching: lowercase, accents removed, every non-alphanumeric character replaced by a space, spaces collapsed. Keywords are normalized the same way and match only whole words or whole phrases.
5. A title is **relevant** when it matches at least one include keyword and no exclude keyword. Irrelevant jobs are never stored; they are counted as `discarded`.
6. Defaults: include and exclude lists are those in [`_dx.md` › Config](_dx.md#config). The include list must not be empty; the exclude list may be.

**Seniority** (applied to the normalized title)

7. Keyword table:

   | Level    | Keywords (normalized, whole word/phrase)                                          |
   | -------- | --------------------------------------------------------------------------------- |
   | `intern` | `estagio`, `estagiario`, `estagiaria`, `intern`, `internship`                     |
   | `junior` | `junior`, `jr`, `trainee`                                                         |
   | `mid`    | `pleno`, `mid`, `mid level`                                                       |
   | `senior` | `senior`, `sr`, `especialista`, `specialist`, `lead`, `lider`, `tech lead`, `principal`, `staff` |

8. When several keywords match, the one starting left-most in the title wins. No match means `null`. "pl" is deliberately not a keyword (it would match "PL/SQL").

**Lifecycle**

9. A job is **active** when `now − last_seen_at ≤ JOB_INACTIVE_AFTER_DAYS` (default 7 days). Activity is evaluated at read time, never stored, so a job collected again is active again with no extra step.
10. Jobs are never deleted by the system.

**Collection runs**

11. Run states: `running` → one of `success`, `partial`, `failed`. No other transition exists, and a finished run never changes again.
12. Final status: all combinations `success` → `success`; at least one `failed` and at least one `success` → `partial`; all `failed`, or the run failed as a whole (crawl crash, ingest failure, signal, interruption; rules 24–26) → `failed`.
13. At most one run is `running` at any time. A start attempt while another run is `running` is refused (CLI exit `3`) and records nothing. The exception: a `running` run older than `SCRAPE_RUN_TIMEOUT_MINUTES` (default 60) is first marked `failed` with error `interrupted`. This takeover can only hit a dead process, because rule 25 stops every live crawl 10 minutes before that age.
14. Run triggers:
    - `scheduled`: the daily cron.
    - `startup`: scheduler start, when `SCRAPE_ON_START=true` and either the job store is empty or no run has finished (`success`, `partial` or `failed`) with a `started_at` in the last 24 hours. The second condition was added after review round 1, issue 004, by the user's decision.
    - `manual`: the CLI.
15. The cron itself never replays a slot that was missed while the scheduler was down. Recovery is done by the start-up rule in rule 14: a scheduler that comes back after a missed 06:00 collects on start when no run finished in the last 24 hours. Failed combinations are never retried within the same run; the next run tries them again.

**Scraping conduct**

16. robots.txt is obeyed. Requests to the same site are at least `SCRAPE_DOWNLOAD_DELAY` seconds apart (default 1.0; values below 1.0 are rejected). At most one request is in flight per site.
17. Per source × term, at most `SCRAPE_MAX_PAGES` listing pages (default 20). Collection for a term also stops when a page brings no job not already seen for that term in this run, or when the site exposes no next page.
18. Only the public listing pages are read. No login, and no job detail pages.

**Search**

19. Text search (`q`) and location matching are substring matches, ignoring case and accents. User input is always matched literally.
20. Parameters combine with AND. Repeated values of one parameter (`source`, `seniority`) combine with OR.
21. Period filter: a job matches `seen_from`/`seen_to` when `first_seen_at` is on or before the end of `seen_to` and `last_seen_at` is on or after the start of `seen_from`, with dates taken in `SCRAPE_TIMEZONE`. `seen_from` must be on or before `seen_to`.
22. Pagination: `page` ≥ 1; `size` 1–100, default 20. Ordering: `last_seen_at` desc, `first_seen_at` desc, `id` desc.

**Permissions**

23. Every API endpoint is public and read-only. No endpoint creates, changes or deletes data, or triggers a collection.

**Run robustness** (added after review round 1; numbered after rule 23 so existing references stay stable)

24. A run stopped by SIGTERM or SIGINT at any phase **from `start_run` on** has the effects below. A signal during `start_run` lets it finish, so the CLI always gets a `run_id`, and the run is then recorded as interrupted (review round 4, issue 001).
    - The collector process is the only signal handler. The crawl child ignores SIGINT and has no Scrapy signal handlers.
    - **During the crawl:** the collector sends SIGTERM to the child, waits at most 5 seconds, then SIGKILLs it. It does not wait for in-flight requests.
    - **During ingestion:** the signal cancels the ingestion task before its commit, and the transaction is rolled back. A signal that lands after the commit is a late signal: the finished run stands.
    - In both cases, the run is then recorded `failed` with error `interrupted by signal`, in a fresh transaction, and the process exits `4`. This holds whatever the child reported, so a stopped crawl is never recorded `success`.
    - The whole sequence completes in well under the scheduler's 25-second wait: at most 5 s for the child, plus `fail_run`. CLI engines are created with a 5-second connect timeout (`create_async_engine(..., connect_args={"timeout": 5})` in `infrastructure.db.session.make_engine`), so `fail_run` cannot hang on an unreachable database.
    - A signal received between two phases has the same effect, because the CLI checks the stop flag after each non-terminal phase (`start_run`, the crawl). A signal after a terminal phase (`complete_run` committed, or a crash or ingest-failure `fail_run`) does not change the run, and the CLI keeps that phase's exit code.
    - The scheduler forwards SIGTERM to a running collector and waits for it to exit.

    Only SIGKILL (or a host crash) can still leave a run `running`; rule 13 then covers it. Revised after review round 2, reopened issue 003.
25. A run's crawl is limited to `SCRAPE_RUN_TIMEOUT_MINUTES − 10` minutes, 50 by default. When the limit is reached:
    - the crawl stops;
    - every source × term combination that had not reached its own stop condition (rule 17) is `failed` with error `run time limit reached`;
    - jobs already collected are ingested normally, and the run ends `partial` or `failed` per rule 12.

    Each request times out after 30 seconds.
26. If ingestion fails, the run is recorded `failed` with error `ingest failed: <ExceptionType>: <message>` in a fresh transaction, no job from that run is stored, and the CLI exits `1`.
27. Scraped text is sanitized before it reaches storage:
    - NUL characters are removed from every field.
    - A card whose site id is longer than 64 characters is skipped, like a card without an id (US-001.EC-1).
    - No other length limit applies to job text.
28. An error while parsing a listing page fails only that source × term combination, with error `parse error: <ExceptionType>: <message>`. Pagination for that term stops, and jobs from its earlier pages are kept. Other terms and sources continue.

## User Experience

- **Technical evaluator:** README first screen → `docker compose up --build` → logs show the startup collection → `http://localhost:8000/docs` → search → "v1 → v2" section and `docs/tasks/fastapi-refactor/`. Target: real data in ≤ 15 minutes (O4).
- **API consumer:** `GET /jobs` with text and filters → page through → `GET /jobs/{id}` → follow `url`.
- **Maintainer:** edit `.env` → restart → `take-jobs collect` or wait for the schedule → `GET /collection-runs` → inspect failures in `GET /collection-runs/{id}`.
- **Credentials:** v1 committed a MySQL password. It remains in git history at `52018b3`, which the `v1` tag points to. The user confirmed on 2026-10-30 that this password is no longer used anywhere. It is treated as leaked, and no artifact, README, review file or log may ever quote its value; references cite file paths only.
- **Accessibility:** no graphical UI. The README uses descriptive headings and alt text for any images.
- **Discoverability:** interactive OpenAPI docs; `.env.example` documents every setting; the CLI's `--help` documents its options.

## High-Level Technical Constraints

- **Fixed by the user:**
  - FastAPI in a layered architecture with dependency injection.
  - PostgreSQL with SQLAlchemy 2 and Alembic.
  - Docker Compose; uv, ruff, pytest; GitHub Actions.
  - JSON-only API with no WebSocket.
  - English everywhere except the search terms.
- **Integrations:** public listing pages of vagas.com and Infojobs, whose HTML may change without notice.
- **Performance:** search p95 < 300 ms with 50,000 jobs locally (O7). A full default run completes in about 10 minutes (≈ 480 requests at 1 req/s per site, two sites in parallel).
- **Security:**
  - No committed secrets.
  - No user input reaches a shell.
  - The database port is not published to the host.
- **Privacy:** only public job posting data is stored; nothing about users is collected.
- **Operability outside a UI:** the maintainer operates everything through the CLI (`take-jobs collect`), the run-history API, environment configuration, and structured logs.
- **Extension ecosystem:** none for third parties. Internally, sources are pluggable (US-007).

## Non-Goals (Out of Scope)

User decisions recorded in the PRD (Q21 in the RUN_LOG):

- Real-time streaming (WebSocket) and any HTML frontend.
- Authentication, multi-user support and cloud deployment.
- Managing search terms through the API.
- Stack classification and relevance ranking.
- Job detail pages, salary and full requirements.
- Job boards other than vagas.com and Infojobs.
- Notifications.
- Migration of v1 MySQL data.
- Same-day retries.

Also excluded by this spec: triggering collections through the HTTP API (rule 23), because the API is read-only.

## Open Questions

None open.

- **OQ-1 — User-Agent identity (resolved 2026-10-30).** The user approved the recommendation: the default `SCRAPE_USER_AGENT` identifies the bot honestly, as `take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)`. If the fixture-capture task shows either site blocking it, the implementer stops and returns to the user before switching to a browser-like UA. It must not switch silently.

---

# Part II — Technical

## Executive Summary

v2 is a single Python 3.13 package, `take_jobs`, with four layers and three entry points:
- **Layers:** `domain` (pure rules and ports), `application` (use cases), `infrastructure` (PostgreSQL via async SQLAlchemy, Scrapy spiders), and the delivery adapters `api` (FastAPI) and `cli`.
- **Entry points:** the FastAPI app factory, `take-jobs collect` and `take-jobs scheduler`.

Dependency injection uses FastAPI `Depends` chains in the API and an explicit composition function in the CLI. Domain and application code only see `Protocol` ports, so every use case is unit-tested with in-memory fakes. [ADR-001](adrs/adr-001.md) records why the layer boundaries are enforced in CI with import-linter.

Collection runs in three phases: **start run (async DB) → crawl (Scrapy, in a spawned child process) → ingest (async DB)**. Scrapy never touches the database. The child process isolates the non-restartable Twisted reactor, so `main()` can run many times in one Python process (as tests need) and a signal can stop the crawl cleanly ([ADR-002](adrs/adr-002.md)). Each source is one spider that walks every term, so the per-site rate limit holds ([ADR-003](adrs/adr-003.md)). A dedicated `scheduler` container runs APScheduler and launches `take-jobs collect` as a subprocess, with no shell ([ADR-004](adrs/adr-004.md)). Jobs are deduplicated on `(source, external_id)` with a PostgreSQL upsert. Accent-insensitive search uses an `unaccent` + `pg_trgm` indexed generated column ([ADR-005](adrs/adr-005.md)). The main trade-off is that a run's jobs become visible only when the whole crawl ends; in exchange, Scrapy never shares an event loop or connections with SQLAlchemy.

## MVP Boundary

The MVP is the whole PRD, because every FR is in scope and the slices below are an ordering, not a cut. **Slice 1** ships first and solves the Motivating Problem: `docker compose up --build`, followed by `take-jobs collect`, stores vagas.com jobs, and `GET /jobs` returns them with text search and pagination. Infojobs, relevance, seniority, lifecycle, the remaining filters, run history, the scheduler and the startup run, CI, README and the `v1` tag follow in later slices of `_tasks.md`. There is no post-MVP work inside this spec. Everything excluded is listed in Non-Goals and stays out of scope; no wanted capability is deferred.

## Developer Experience

- [Developer experience contract](_dx.md):
  - **Golden Path:** clone → `docker compose up --build` → search.
  - **CLI:** `take-jobs collect` (`--trigger`, `--json`, exit codes 0/1/2/3/4) and `take-jobs scheduler`.
  - **HTTP API:** `GET /jobs`, `GET /jobs/{job_id}`, `GET /collection-runs`, `GET /collection-runs/{run_id}`, `GET /health`, `GET /docs`, `GET /openapi.json`.
  - **Config:** all environment keys and their defaults.
  - **Errors:** the unified HTTP error shape and the CLI messages.
- No UI: `_uiux.md` does not apply.

## System Architecture

```text
                    ┌──────────────── docker compose ────────────────┐
                    │                                                 │
  curl / Swagger ──►│  api  (uvicorn take_jobs.api.app:create_app)    │
                    │    routers → application services → repos ──┐  │
                    │                                             ▼  │
                    │  db  (postgres:17, volume pgdata)  ◄── migrate (alembic upgrade head, one-shot)
                    │                                             ▲  │
                    │  scheduler (take-jobs scheduler)            │  │
                    │    APScheduler cron ──subprocess──► take-jobs collect
                    │                                     │  1. start run ───────┘
                    │                                     │  2. crawl (Scrapy, spawned child) ──► vagas.com, infojobs.com.br
                    │                                     │  3. ingest report ───► db
                    └─────────────────────────────────────────────────┘
```

| Component | Responsibility | Boundaries |
| --- | --- | --- |
| `domain` | Entities, value objects, normalization, relevance filter, seniority classifier, run-status rules, ports (`Protocol`s) | Pure Python; no I/O, no frameworks |
| `application` | Use cases: `JobQueryService`, `CollectionRunQueryService`, `CollectionService` | Depends only on `domain`; time comes in via the `Clock` port |
| `infrastructure.db` | SQLAlchemy models, engine/session factory, `SqlAlchemyJobRepository`, `SqlAlchemyCollectionRunRepository`, `SqlAlchemyJobStoreProbe` | Implements domain ports; Alembic migrations live in `migrations/` |
| `infrastructure.scraping` | Source registry, per-source HTML parsers (pure functions), Scrapy spiders, `ScrapyJobScraper` (implements `JobScraper`) | Never imports `infrastructure.db`; returns a `ScrapeReport` |
| `api` | App factory, lifespan (engine), routers, request/response schemas, DI providers, error handlers | Composition root for HTTP |
| `cli` | `collect` and `scheduler` commands; composition root for processes | Composition root for CLI |
| `config` | `Settings` (pydantic-settings), validation of every key in `_dx.md` › Config | Read only by composition roots |

**Data flow of a run:**
1. `cli.collect` receives `CliDeps`: the defaults from `build_cli_deps(settings)`, or test doubles. Before the first phase, it installs **one** process-wide handler for SIGTERM and SIGINT with `signal.signal`, which stays installed for the whole command (rule 24; review round 3, reopened issue 003).
   - **On a signal,** the handler sets a `stop_requested` flag and dispatches by the current phase, which the CLI tracks in a phase-scoped reference:
     - during the crawl, it calls `scraper.interrupt()`;
     - during `start_run` (step 2), and during any `fail_run`, it **only** sets the flag. These phases are never cancelled; each is bounded by the 5-second connect timeout (review round 4, issue 001);
     - during `complete_run`, while the phase reference is marked `cancellable`, it calls `loop.call_soon_threadsafe(main_task.cancel)` on that phase's loop and task. The CLI passes `before_commit=phase.clear_cancellable` to `CollectionService.complete_run`, which calls it as the **last statement inside its `async with uow:` block**, after `runs.finish`, so the UoW's `__aexit__` commits right after it. A cancel queued after the hook ran never starts. A cancel queued just before the hook ran can still be delivered during the commit, and the status re-read below covers that case (review rounds 5–6);
     - between phases, it only sets the flag;
     - while `fail_run` is recording an interruption, it ignores further signals.
   - **Restrictions:**
     - `loop.add_signal_handler` is **never** used: when its loop closes, it resets the signal to the default action instead of restoring the previous handler.
     - Because the installed SIGINT handler is not `default_int_handler`, `asyncio.run` leaves it alone.
   - **After each non-terminal phase** — `start_run` and the crawl, while the run is known to be `running` — the CLI checks `stop_requested`. If it is set, the CLI skips the remaining phases, records `interrupted by signal` and exits `4`. This covers a signal that lands between phases, for example right after `scrape()` returns.
   - **After a terminal phase** — `complete_run` returned, or any `fail_run` (crash, ingest failure) returned — a set flag is a late signal. The CLI logs `signal_after_finish` and keeps that phase's exit code (`0` or `1`). It never calls `fail_run` a second time (review round 5, issue 002).
   - **Late signals:** a signal that arrives after `complete_run` committed does not change the finished run. The CLI logs `signal_after_finish` and exits with the run's normal code.
   - **Status re-read:** whenever a phase ends with `CancelledError`, the CLI re-reads the run before reporting. It uses `CollectionService.get_run(run_id)` through a fresh `open_collection_service()`, so unit tests control the result with the same fake service.
     - If the run is already finished, the commit landed. This is the late-signal case: log `signal_after_finish` and exit with that run's code.
     - If the run is still `running`, record `interrupted by signal` and exit `4`.
     - The "taken over by another process" message is printed only when `complete_run` itself raises `RunTakenOverError`, never after a cancellation.
2. `asyncio.run(CollectionService.start_run(trigger, expected_combinations=len(sources) × len(terms)))` returns `run_id`, or refuses because a run is already active.
3. `ScrapyJobScraper.scrape(terms)` starts a `multiprocessing` child with the `spawn` start method, over a one-way `Pipe(duplex=False)`.
   - **In the child:**
     - It sets SIGINT to `SIG_IGN`, so a terminal Ctrl+C reaches only the collector. SIGTERM keeps its default action, which terminates the child immediately.
     - It runs the optional test `child_initializer`.
     - It runs one `CrawlerProcess`, with one spider per source in parallel, using `process.start(install_signal_handlers=False)`, so Scrapy never installs its graceful-shutdown handlers.
     - It sends the `ScrapeReport` (picklable dataclasses) through the pipe, then exits `0`.
   - **Hand-off order in the parent** (review round 2, issue 001). Waiting for the child to exit before reading deadlocks as soon as the report exceeds the pipe buffer.
     1. Right after `start()`, the parent closes its copy of the child's end of the pipe.
     2. It waits with `multiprocessing.connection.wait([conn, process.sentinel])` and reads the report with `conn.recv()` **before** `process.join()`.
     3. When the read ends in EOF or `process.sentinel` fires with no report, it raises `ScrapeCrashedError`, naming the child's exit code.
   - **Result:**
     - returns the report when the child sent one and exited `0`;
     - raises `ScrapeCrashedError` when the child exited without a report;
     - raises `ScrapeInterruptedError` when the collector received a signal during the crawl, **whatever the child sent** (rule 24).
4. `asyncio.run(CollectionService.complete_run(run_id, report))` processes each combination: relevance filter → seniority → upsert (yields new or seen-again) → result row. It then computes the final status and finishes the run, all in one transaction.
5. Failure paths, each followed by `asyncio.run(CollectionService.fail_run(run_id, error))` in a fresh transaction:

   | Path | Recorded error | Exit code |
   | --- | --- | --- |
   | Step 3 raises `ScrapeCrashedError` | crash message | `1` |
   | Step 4 raises (rule 26) | `ingest failed: …` | `1` |
   | A signal arrives from step 2 on, while the run is still `running` (rule 24) | `interrupted by signal` | `4` |
   | A signal arrives after a terminal phase (`complete_run` committed, or a crash or ingest-failure `fail_run`) | unchanged; `signal_after_finish` is logged | that phase's code |

   If `finish` affects 0 rows because another process took the run over (rule 13), the CLI prints `Collection run <N> was taken over by another process; its results were discarded.` and exits `1`.

**Compose contract** (`docker-compose.yml`):

| Service | Image / command | Depends on | Other |
| --- | --- | --- | --- |
| `db` | `postgres:17`, volume `pgdata`, `environment:` `POSTGRES_USER: ${POSTGRES_USER-take_jobs}` etc. | — | healthcheck `["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]`. The `$$` makes the container's shell expand the variables instead of Compose (review round 2, issue 003). Interval 5 s, timeout 3 s, retries 12; **no `ports:`** |
| `migrate` | app image, `alembic upgrade head` | `db: condition: service_healthy` | `restart: "no"` |
| `api` | app image, `uvicorn --factory take_jobs.api.app:create_app --host 0.0.0.0 --port 8000` | `migrate: condition: service_completed_successfully` | `ports: ["${API_PORT-8000}:8000"]`, `restart: unless-stopped` |
| `scheduler` | app image, `take-jobs scheduler` | `migrate: condition: service_completed_successfully` | `init: true`, `stop_grace_period: 30s`, `restart: unless-stopped` |

No `env_file:`. Every application key is listed under each service's `environment:` as `${KEY-default}` (Config Lifecycle). Compose reads the project's `.env`, when present, for interpolation.

**Scheduler start-up** (order fixed in review round 3, reopened issue 003):
1. **Install the shutdown handler first.** The scheduler creates its scheduler object with `deps.scheduler_factory()`, without starting it, and installs `make_shutdown_handler` for SIGTERM and SIGINT. From then on, any signal reaches whichever collector is running, including the startup collection.
2. **Wait for the database.** `wait_for_database` pings it, retrying with backoff (1, 2, 4, 8, 10, 10 … seconds) for up to 60 seconds in total and logging `startup_probe_failed` on each attempt. If it still fails, the scheduler exits `1`, and the restart policy brings it back.
3. **Register the cron job** with `configure_scheduler`, and log `scheduler_started` with its next fire time.
4. **Apply rule 14** with `run_startup`, which may run the startup collection through the runner and blocks while it runs.
5. **Start the scheduler loop** with `scheduler.start()`.

## Architectural Boundaries

Packages under `src/take_jobs/`:

| Package | May import | Must not import |
| --- | --- | --- |
| `take_jobs.domain` | stdlib only | anything else in `take_jobs`; `fastapi`, `sqlalchemy`, `scrapy`, `pydantic` |
| `take_jobs.application` | `take_jobs.domain` | `take_jobs.infrastructure`, `take_jobs.api`, `take_jobs.cli`, `take_jobs.config`, frameworks |
| `take_jobs.infrastructure.db` | `take_jobs.domain`, `sqlalchemy` | `take_jobs.application`, `take_jobs.api`, `take_jobs.cli`, `take_jobs.config`, `take_jobs.infrastructure.scraping` |
| `take_jobs.infrastructure.scraping` | `take_jobs.domain`, `scrapy`, `parsel` | `take_jobs.application`, `take_jobs.api`, `take_jobs.cli`, `take_jobs.config`, `take_jobs.infrastructure.db` |
| `take_jobs.api` | `take_jobs.application`, `take_jobs.domain`, `take_jobs.config`; `take_jobs.infrastructure` **only** from `take_jobs.api.dependencies` and `take_jobs.api.app` | `take_jobs.cli` |
| `take_jobs.cli` | everything except `take_jobs.api` | `take_jobs.api` |
| `take_jobs.config` | `pydantic_settings`, `take_jobs.domain` (for `Seniority`/source validation) | other `take_jobs` packages |

Composition roots:
- HTTP: `take_jobs.api.app:create_app` together with `take_jobs.api.dependencies`.
- Processes: `take_jobs.cli.main:main`, exposed as the `take-jobs` script. `take_jobs/__main__.py` contains only `from take_jobs.cli.main import main; raise SystemExit(main())`, so `python -m take_jobs` works (Safety Invariant 6).

These rules are enforced as `import-linter` contracts in `pyproject.toml` and run in CI ([ADR-001](adrs/adr-001.md)).

## Implementation Design

### Core Interfaces

```python
# take_jobs/domain/models.py
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    STARTUP = "startup"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScrapedJob:
    source: str  # registered source id, e.g. "vagas"
    external_id: str  # the site's own job id
    title: str
    url: str
    company: str | None
    location: str | None
    description: str | None
    published_label: str | None  # publication date as displayed by the site


@dataclass(frozen=True, slots=True)
class CombinationOutcome:
    source: str
    term: str
    jobs: tuple[ScrapedJob, ...]  # in collection order, may contain repeats
    pages: int
    error: str | None  # None = success


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    outcomes: tuple[CombinationOutcome, ...]  # one per source × term


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    source: str
    external_id: str
    title: str
    url: str
    company: str | None
    location: str | None
    description: str | None
    published_label: str | None
    seniority: Seniority | None
    first_seen_at: datetime
    last_seen_at: datetime

    def is_active(self, now: datetime, inactive_after: timedelta) -> bool:
        return now - self.last_seen_at <= inactive_after


@dataclass(frozen=True, slots=True)
class JobSearchCriteria:
    text: str | None = None
    sources: frozenset[str] = frozenset()
    location: str | None = None
    seniorities: frozenset[Seniority] = frozenset()
    seen_from: datetime | None = None  # start of day in SCRAPE_TIMEZONE, as UTC
    seen_to: datetime | None = None  # end of day in SCRAPE_TIMEZONE, as UTC
    active_since: datetime | None = None  # None = include inactive
    page: int = 1
    size: int = 20


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: tuple[T, ...]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return -(-self.total // self.size)


@dataclass(frozen=True, slots=True)
class CombinationResult:
    source: str
    term: str
    status: ResultStatus
    pages: int
    new: int
    seen_again: int
    discarded: int
    error: str | None


@dataclass(frozen=True, slots=True)
class RunTotals:
    new: int
    seen_again: int
    discarded: int

    @classmethod
    def from_results(
        cls, results: Sequence[CombinationResult]
    ) -> RunTotals: ...  # sums; zeros when empty


@dataclass(frozen=True, slots=True)
class CollectionRun:
    id: int
    trigger: RunTrigger
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    expected_combinations: int  # sources × terms at start; denominator for O5
    totals: RunTotals  # filled by the repository from an aggregate over results,
    # so list views carry real totals while `results` is empty
    results: tuple[CombinationResult, ...]  # empty while running and in list views
```

```python
# take_jobs/domain/ports.py
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...  # timezone-aware UTC


class JobRepository(Protocol):
    async def upsert(self, job: ScrapedJob, seniority: Seniority | None, seen_at: datetime) -> bool:
        """Insert or refresh by (source, external_id). Returns True when inserted (new)."""

    async def get(self, job_id: int) -> Job | None: ...
    async def search(self, criteria: JobSearchCriteria) -> Page[Job]: ...


class JobStoreProbe(Protocol):
    async def is_empty(self) -> bool: ...
    async def ping(self) -> None: ...  # raises on an unreachable database


class CollectionRunRepository(Protocol):
    async def start(
        self, trigger: RunTrigger, started_at: datetime, expected_combinations: int
    ) -> int:
        """Create a running run. Raises RunAlreadyActiveError(run_id, started_at)."""

    async def get_active(self) -> CollectionRun | None: ...
    async def latest_finished(self) -> CollectionRun | None:
        """Most recently started run whose status is not running (rule 14)."""

    async def mark_interrupted(self, run_id: int, finished_at: datetime) -> None: ...
    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        results: Sequence[CombinationResult],
        finished_at: datetime,
        error: str | None,
    ) -> None:
        """Conditional on status = 'running'. Raises RunTakenOverError when 0 rows are affected."""

    async def get(self, run_id: int) -> CollectionRun | None: ...
    async def list(self, page: int, size: int) -> Page[CollectionRun]: ...


class UnitOfWork(Protocol):
    jobs: JobRepository
    runs: CollectionRunRepository
    probe: JobStoreProbe  # same session; used by CollectionService.ping/startup_reason

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...  # commit on success, rollback on error


class JobScraper(Protocol):
    def scrape(self, terms: Sequence[str]) -> ScrapeReport:
        """Blocking. One outcome per registered source × term. Never touches the database.
        Raises ScrapeInterruptedError (a signal stopped it) or ScrapeCrashedError (no report)."""

    def interrupt(self) -> None:
        """Called from the collector's signal handler; stops a running crawl within 5 s (rule 24).
        Called before the child exists, it records the request: scrape() then raises
        ScrapeInterruptedError without crawling (checked before and right after process.start())."""
```

```python
# take_jobs/domain/rules.py — pure functions and policies
def normalize(text: str) -> str: ...


class RelevancePolicy:
    def __init__(
        self, include: Sequence[str], exclude: Sequence[str]
    ) -> None: ...  # ValueError if include empty
    def is_relevant(self, title: str) -> bool: ...


def classify_seniority(title: str) -> Seniority | None: ...
def final_run_status(results: Sequence[CombinationResult]) -> RunStatus: ...
def startup_collection_reason(
    store_empty: bool, latest_finished_started_at: datetime | None, now: datetime
) -> Literal["empty_job_store", "no_recent_run"] | None:
    """Rule 14. Empty store first. Otherwise no finished run, or the latest started more than 24 h before now."""


def to_standard_crontab(expr: str) -> str:
    """Make the day-of-week field follow standard cron under APScheduler's from_crontab
    (whose numbering and name ranges are Monday-first).
    The field is parsed as standard cron: numbers 0–7 with 0 and 7 = Sunday, names sun–sat, ranges,
    lists and steps. It is re-emitted as an explicit comma list of names in Sunday-first order
    (e.g. "0-4" → "sun,mon,tue,wed,thu"), so no emitted range can wrap. "*" stays "*".
    Raises ValueError for an invalid field. Other fields are unchanged."""
```

```python
# take_jobs/application/services.py
class JobQueryService:
    def __init__(
        self, jobs: JobRepository, clock: Clock, inactive_after: timedelta, tz: ZoneInfo
    ) -> None: ...
    async def search(
        self, query: JobQuery
    ) -> Page[JobView]: ...  # JobQuery = raw API inputs; raises InvalidPeriodError
    async def get(self, job_id: int) -> JobView: ...  # raises JobNotFoundError


class CollectionRunQueryService:
    def __init__(self, runs: CollectionRunRepository) -> None: ...
    async def list(self, page: int, size: int) -> Page[CollectionRun]: ...
    async def get(self, run_id: int) -> CollectionRun: ...  # raises CollectionRunNotFoundError


class CollectionService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        relevance: RelevancePolicy,
        clock: Clock,
        run_timeout: timedelta,
    ) -> None: ...
    async def start_run(self, trigger: RunTrigger, expected_combinations: int) -> int:
        ...
        # interrupts a stale run; raises RunAlreadyActiveError

    async def complete_run(
        self, run_id: int, report: ScrapeReport, *, before_commit: Callable[[], None] | None = None
    ) -> CollectionRun:
        ...
        # one transaction; calls before_commit() synchronously as the last statement inside `async with uow:`
        # (after runs.finish), so UnitOfWork.__aexit__ commits right after it; not called when finish raises;
        # raises RunTakenOverError

    async def get_run(self, run_id: int) -> CollectionRun | None:
        ...
        # one UoW → uow.runs.get(run_id); used by the CLI's re-read after a cancelled phase

    async def fail_run(self, run_id: int, error: str) -> CollectionRun:
        ...
        # fresh transaction; results stay empty

    async def startup_reason(self) -> str | None:
        ...
        # rule 14: one UoW → startup_collection_reason(uow.probe.is_empty(), uow.runs.latest_finished(), clock.now())

    async def ping(self) -> None:
        ...
        # one UoW → uow.probe.ping(); raises on an unreachable database (used by wait_for_database)
```

`JobView` is `Job` plus the computed `active: bool`. Errors are split by origin:
- `take_jobs.application.errors`: `JobNotFoundError`, `CollectionRunNotFoundError`, `InvalidPeriodError`.
- `take_jobs.domain.errors`, because ports raise them: `RunAlreadyActiveError`, `RunTakenOverError` (repositories), `ScrapeInterruptedError` and `ScrapeCrashedError` (scraper). The application package re-exports them. The API maps each one to the `_dx.md` error codes.

```python
# take_jobs/infrastructure/scraping/registry.py
@dataclass(frozen=True, slots=True)
class SourceDefinition:
    id: str  # "vagas" | "infojobs"
    spider: type[
        scrapy.Spider
    ]  # walks every term itself; importable top-level class (picklable for spawn)
    base_url: str  # real site origin, e.g. "https://www.vagas.com.br"


SOURCES: Mapping[str, SourceDefinition]  # adding a site = parser + spider + one entry here (US-007)


def with_base_url(
    sources: Mapping[str, SourceDefinition], base_url: str
) -> Mapping[str, SourceDefinition]:
    """Test seam: the same sources pointed at a local fixture server (FR-30). Not a config key."""


# Every spider takes: terms: Sequence[str], max_pages: int, base_url: str.
# Spider state per term: seen ids, pages, finished flag, error.
# Errors reach that state through request errbacks (HttpError, IgnoreRequest from robots.txt,
# timeouts) and through the spider_error signal for exceptions raised in callbacks
# (rule 28; mandatory, ADR-002).


class ScrapyJobScraper:  # implements JobScraper
    def __init__(
        self,
        sources: Mapping[str, SourceDefinition],
        settings: ScrapeSettings,
        *,
        child_initializer: Callable[[], None] | None = None,
    ) -> None: ...

    # child_initializer: optional top-level callable run first in the child. It is a test seam only,
    # e.g. installing the pytest-socket guard in the child (FR-30).
    # scrape(): spawn child → CrawlerProcess(...).start(install_signal_handlers=False) → report
    # through a pipe, read BEFORE join (data flow step 3).
    # Close-reason handling in the child:
    #   "finished" → per-term outcomes as recorded; a term that never finished (Scrapy dropped its
    #     request without calling the errback, e.g. the duplicate filter) gets error
    #     "crawl closed: finished before the term completed" (review round 7, issue 002);
    #   "closespider_timeout" → unfinished terms get error "run time limit reached" (rule 25);
    #   any other reason → every unfinished term gets "crawl closed: <reason>".
    # Signals are never handled in the child (rule 24).
    # interrupt(): called by the collector's signal handler during the crawl. Sets interrupt_requested;
    # if the child is alive, sends SIGTERM, polls for up to 5 s, then SIGKILLs; scrape() then raises
    # ScrapeInterruptedError. If the child does not exist yet, scrape() sees interrupt_requested before
    # and right after process.start() and terminates it at once (review round 4, issue 001).
```

```python
# take_jobs/cli/main.py — composition seams (issue 001)
@dataclass(frozen=True)
class CliDeps:
    settings: Settings
    sources: Mapping[str, SourceDefinition]
    relevance: RelevancePolicy  # built from settings; observable for UT-077
    scraper: JobScraper  # ScrapyJobScraper(sources, settings) by default
    open_collection_service: Callable[[], AbstractAsyncContextManager[CollectionService]]
    # builds and disposes a fresh engine on every call (Safety Invariant 5); uses `relevance` and `clock`
    clock: Clock  # SystemClock by default
    runner: CollectionRunner  # scheduler only: Popen of `python -m take_jobs collect`
    sleep: Callable[[float], None]  # scheduler probe backoff; time.sleep by default
    scheduler_factory: Callable[
        [], BaseScheduler
    ]  # BlockingScheduler by default; tests pass a stub


def build_cli_deps(
    settings: Settings,
    sources: Mapping[str, SourceDefinition] = SOURCES,
    *,
    child_initializer: Callable[[], None] | None = None,
) -> CliDeps:
    ...
    # child_initializer is passed to ScrapyJobScraper; tests only (network guard in the crawl child)


def main(argv: Sequence[str] | None = None, *, deps: CliDeps | None = None) -> int:
    ...
    # deps None → build_cli_deps(Settings()); invalid config → exit 2


# take_jobs/cli/scheduler.py — scheduler seams (review round 2, issue 004)
def wait_for_database(
    open_service: Callable[[], AbstractAsyncContextManager[CollectionService]],
    *,
    sleep: Callable[[float], None],
    max_wait_s: float = 60,
) -> None:
    ...
    # each attempt: asyncio.run(<async with open_service() as s: await s.ping()>) with a fresh engine;
    # backoff 1, 2, 4, 8, 10, 10 … s; logs startup_probe_failed; raises DatabaseUnavailableError after max_wait_s


class CollectionRunner(Protocol):  # take_jobs/cli/runner.py (review round 3, issue 001)
    def run(self, trigger: RunTrigger) -> int:
        ...
        # starts the collector, blocks until it exits, returns its exit code

    def terminate_current(self, wait_s: float) -> None:
        ...
        # SIGTERM to the running collector, if any; polls proc.poll() every 0.2 s for up to wait_s,
        # then SIGKILLs; no-op when idle. Never Popen.wait(timeout=…), see run().


class SubprocessCollectionRunner:  # implements CollectionRunner
    current: (
        subprocess.Popen[bytes] | None
    )  # the running collector, set by run() and cleared on exit
    # run(): Popen([sys.executable, "-m", "take_jobs", "collect", "--trigger", trigger.value], shell=False),
    # then `while proc.poll() is None: time.sleep(0.2)`. Never a blocking Popen.wait(): in the main thread
    # (startup run) it holds Popen's waitpid lock while the signal handler runs, so the handler's own wait
    # could never succeed and would always hit its timeout (review round 4, issue 002).


def run_startup(deps: CliDeps) -> str | None:
    ...
    # applies rule 14 via CollectionService.startup_reason(); calls deps.runner on a reason; returns it


def configure_scheduler(scheduler: BaseScheduler, deps: CliDeps) -> None:
    ...
    # adds exactly one cron job (to_standard_crontab, timezone, max_instances=1, coalesce=True,
    # misfire_grace_time=3600); does not start it


def make_shutdown_handler(
    scheduler: BaseScheduler, runner: CollectionRunner, *, wait_s: float = 25
) -> Callable[[int, FrameType | None], None]:
    ...
    # if the scheduler is running, shuts it down (wait=False); runner.terminate_current(wait_s); raises SystemExit(0)


def run_scheduler(deps: CliDeps) -> int:
    ...
    # scheduler = deps.scheduler_factory()
    # → signal.signal(SIGTERM/SIGINT, make_shutdown_handler(scheduler, deps.runner))   # FIRST
    # → wait_for_database → configure_scheduler(scheduler, deps) → log scheduler_started
    # → run_startup(deps) → scheduler.start()


# take_jobs/api/app.py
def create_app(
    settings: Settings | None = None, sources: Mapping[str, SourceDefinition] | None = None
) -> FastAPI:
    ...
    # uvicorn --factory calls it with no arguments → Settings() and SOURCES


# take_jobs/infrastructure/scraping/parsers/<source>.py — pure, fixture-tested
@dataclass(frozen=True, slots=True)
class ListingPage:
    jobs: tuple[ScrapedJob, ...]
    next_url: str | None


def parse_listing(html: str, page_url: str) -> ListingPage: ...
```

The set of valid `source` values in the API and config comes from `SOURCES.keys()`, injected at app creation. The API package never names a site.

### Data Models

Migration `0001` creates the extensions `unaccent` and `pg_trgm`, the function `immutable_unaccent(text)` (an `IMMUTABLE` SQL wrapper over `public.unaccent('public.unaccent', $1)`, required by the generated column and the indexes), and the three tables below.

**`jobs`**

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `bigint generated always as identity` PK | Public job id |
| `source` | `varchar(32) not null` | Registered source id |
| `external_id` | `varchar(64) not null` | Site's own job id; identity with `source` (rule 1) |
| `title` | `text not null` | Job title as listed |
| `company` | `text null` | Company name |
| `location` | `text null` | Location as listed |
| `description` | `text null` | Listing summary |
| `published_label` | `text null` | Publication date exactly as displayed (e.g. `28 out`, `09/10/2026`). Unbounded, so a drifting selector cannot fail ingestion (rule 27) |
| `url` | `text not null` | Absolute URL of the original posting |
| `seniority` | `varchar(8) null`, check in (`intern`,`junior`,`mid`,`senior`) | Derived level |
| `first_seen_at` | `timestamptz not null` | First collection time |
| `last_seen_at` | `timestamptz not null` | Last collection time; drives activity |
| `search_text` | `text generated always as (immutable_unaccent(lower(title ‖ ' ' ‖ coalesce(company,'') ‖ ' ' ‖ coalesce(description,'')))) stored` | Accent-/case-insensitive text search target |

Indexes:
- `uq_jobs_source_external_id` unique (`source`, `external_id`): upsert target and deduplication.
- `ix_jobs_recency` (`last_seen_at desc`, `first_seen_at desc`, `id desc`): the default order and the activity filter.
- `ix_jobs_search_text_trgm` GIN (`search_text gin_trgm_ops`): `q` substring search (O7).
- `ix_jobs_location_trgm` GIN (`immutable_unaccent(lower(location)) gin_trgm_ops`): the `location` filter.
- `ix_jobs_source` (`source`) and `ix_jobs_seniority` (`seniority`): equality filters.

**`collection_runs`**

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `bigint generated always as identity` PK | Run id |
| `trigger` | `varchar(16) not null`, check in (`scheduled`,`startup`,`manual`) | What started it |
| `status` | `varchar(16) not null`, check in (`running`,`success`,`partial`,`failed`) | Lifecycle (rule 11) |
| `started_at` | `timestamptz not null` | Start time |
| `finished_at` | `timestamptz null` | Null while running |
| `error` | `text null` | Run-level error: `interrupted`, `interrupted by signal`, `ingest failed: …`, or the crawl crash message |
| `expected_combinations` | `integer not null` check > 0 | Sources × terms when the run started; denominator of O5 even when the run wrote no results |

Indexes:
- `uq_collection_runs_single_running` unique on (`status`) `where status = 'running'`: the database enforces rule 13.
- `ix_collection_runs_started_at` (`started_at desc`).

**`collection_run_results`**

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `bigint generated always as identity` PK | — |
| `run_id` | `bigint not null` FK → `collection_runs.id` on delete cascade | Owner |
| `source` | `varchar(32) not null` | Source id |
| `term` | `text not null` | Search term |
| `status` | `varchar(8) not null`, check in (`success`,`failed`) | Combination outcome |
| `pages` | `integer not null` check ≥ 0 | Listing pages fetched |
| `new_count` | `integer not null` check ≥ 0 | Jobs inserted |
| `seen_again_count` | `integer not null` check ≥ 0 | Jobs refreshed |
| `discarded_count` | `integer not null` check ≥ 0 | Jobs rejected by relevance |
| `error` | `text null` | Failure reason |

Constraint `uq_run_results_combination` unique (`run_id`, `source`, `term`).

**Upsert** (in `SqlAlchemyJobRepository.upsert`): `INSERT … ON CONFLICT (source, external_id) DO UPDATE SET title, company, location, description, published_label, url, seniority = excluded.*, last_seen_at = excluded.last_seen_at RETURNING (xmax = 0) AS inserted`.

**API schemas** (Pydantic, in `take_jobs.api.schemas`):
- `JobOut`: fields exactly as in `_dx.md`.
- `JobPageOut` / `RunPageOut`: `items`, `total`, `page`, `size`, `pages`.
- `RunSummaryOut`: `id`, `trigger`, `status`, `started_at`, `finished_at`, `error`, `totals`.
- `RunDetailOut`: `RunSummaryOut` plus `results: list[CombinationResultOut]`.
- `HealthOut`.
- `ErrorOut`: `error: {code, message, details: list[{field, message}]}`.

### API Endpoints

| Route | Handler | Dependencies | Success | Failures |
| --- | --- | --- | --- | --- |
| `GET /jobs` | `routers.jobs.search_jobs` | `JobQueryService` | `200 JobPageOut` | `422 validation_error`, `422 invalid_period`, `503 database_unavailable` |
| `GET /jobs/{job_id}` | `routers.jobs.get_job` | `JobQueryService` | `200 JobOut` | `404 job_not_found`, `422`, `503` |
| `GET /collection-runs` | `routers.runs.list_runs` | `CollectionRunQueryService` | `200 RunPageOut` | `422`, `503` |
| `GET /collection-runs/{run_id}` | `routers.runs.get_run` | `CollectionRunQueryService` | `200 RunDetailOut` | `404 collection_run_not_found`, `422`, `503` |
| `GET /health` | `routers.health.health` | `JobStoreProbe` | `200 HealthOut` | `503 HealthOut` (3 s timeout on the probe) |

Validation:
- Query parameters are declared with `Annotated[..., Query(...)]` bounds. `source` is validated against the injected registry keys.
- `q` and `location` are stripped; blank means absent.
- Exception handlers translate `RequestValidationError` → `validation_error`, application errors → their codes, SQLAlchemy `OperationalError`/`InterfaceError`/`TimeoutError` → `database_unavailable`, unknown routes (Starlette 404) → `not_found`, and anything else → `internal_error` (logged with traceback).
- Every error documents its response model in OpenAPI.

DI chain in `take_jobs.api.dependencies`:
1. `get_settings` returns `request.app.state.settings`, which `create_app` sets. It is never a process-global cache, so `create_app(settings=…)` in tests governs every dependency and the lifespan engine (review round 2, issue 004).
2. `get_sessionmaker` (from `app.state`, created in the lifespan and disposed on shutdown).
3. `get_session` (one `AsyncSession` per request).
4. Repositories, then services.

Tests override `get_job_query_service`, `get_run_query_service` and `get_job_store_probe` through `app.dependency_overrides`.

## Integration Points

| Service | Purpose | Auth | Errors and retries |
| --- | --- | --- | --- |
| vagas.com.br (`/vagas-de-{slug}`) | Listing pages. Next page from `a#maisVagas@data-url`. Follow-ups need `Referer` (Scrapy sets it) and `X-Requested-With: XMLHttpRequest`, or the site answers 403. The follow-up response, pages 2–20, is the XHR response, which may be an HTML fragment rather than a full page; the parser must handle both, and task 3 captures it as a fixture | None | Scrapy `RetryMiddleware` defaults (2 retries for 5xx/timeouts), `DOWNLOAD_TIMEOUT=30`. A final failure fails the combination with `HTTP <code> <reason>` (HTTP errors), `blocked by robots.txt`, or otherwise `<ExceptionType>: <message>` (e.g. `TimeoutError: …`). An exception in a callback fails it with `parse error: <ExceptionType>: <message>` (rule 28) |
| infojobs.com.br (page 1: `/vagas-de-emprego-{slug}.aspx?page=1`; pages 2+: `/mf-publicarea/VacancyList/GetVacancyListFragment?url=<page URL, percent-encoded>`) | Listing pages. Cards `.js_cardLink` with `data-id`/`data-href`. The HTML URL ignores `page` and returns page 1 for every N (checked live on 2026-10-30, review round 7 issue 001), so pages 2+ are requested the way the site's infinite scroll does: a plain GET of the list-fragment endpoint with `url=` set to `{base_url}/vagas-de-emprego-{slug}.aspx?page=N`. It answers JSON `{"eof": bool, "listFragmentHTML": "<cards>"}`, needs no cookie or extra header, and past the end of the list returns `{"eof": true, "listFragmentHTML": ""}`. The stop rule is "no unseen ids" (rule 17). A JSON body without `listFragmentHTML` is a parse error (rule 28) | None | Same as above |
| robots.txt of both sites | `ROBOTSTXT_OBEY=True` | — | A disallowed request fails the combination with `blocked by robots.txt` |

Slug: normalize the term (rule 4), then join the words with `-`. For example `desenvolvedor .net` → `desenvolvedor-net`. Task 3 verifies each default term's URL against the live sites once, while capturing fixtures (Known Risk R2).

Field mapping (verified against live HTML on 2026-10-30; fixtures pin it):

| Field | vagas.com (`li.vaga`) | Infojobs (`div.js_cardLink`) |
| --- | --- | --- |
| `external_id` | `a.link-detalhes-vaga@data-id-vaga` | `@data-id` |
| `title` | `a.link-detalhes-vaga@title` | `h2.js_vacancyTitle` text |
| `url` | `urljoin(page_url, a.link-detalhes-vaga@href)` | `urljoin(page_url, @data-href)` |
| `company` | `span.emprVaga` text | company link text (`a.text-body.text-decoration-none`) |
| `location` | `div.vaga-local` direct text | first text of the location line (`div.mb-8`) |
| `description` | `div.detalhes p` string (strip `<mark>`) | card summary `div.text-medium` (last) |
| `published_label` | `span.data-publicacao` text | `div.text-medium.small.text-nowrap` text |

All text is whitespace-collapsed and stripped. An empty string becomes `None`. A card without `external_id` or `title` is skipped (US-001.EC-1).

**URL resolution** (review round 2, reopened issue 010). This guarantees that tests pointed at a fixture server can never reach the real site.
- Every URL taken from a page (job `url`, vagas `next_url`) is resolved with `urljoin(page_url, value)` against the URL of the page being parsed. No parser hard-codes a site origin; v1 built the vagas next page from a hard-coded `https://www.vagas.com.br`.
- Each spider sets `allowed_domains` from its `base_url` host.
- A follow-up request whose origin differs from `base_url` is not issued; the term fails with `parse error: OffOriginURLError: <url>` (rule 28).

## Impact Analysis

| Component | Impact Type | Description and Risk | Required Action |
| --- | --- | --- | --- |
| `src/sync_app/` (Flask app, models, controllers, templates, Scrapy project, `teste.json`) | deleted | Entire v1 HTTP app and bots. Low risk: preserved by tag `v1` | Hard cut in this change (already staged); no shim |
| `src/async_app/` (WebSocket relay) | deleted | Real-time relay; PRD Non-Goal | Hard cut; no shim |
| v1 routes `/home`, `/jobs/<search>/`, `/takejobs/<search>/<page>/<limit>`, `/takejobssocket/` | deleted public surface | Breaking for any v1 client. The default policy would keep them for one release; **the user decided** on a clean v2 without migration (PRD Non-Goals; RUN_LOG Q12b/Q21). v1 remains runnable from tag `v1` | Remove; document in README "v1 → v2" |
| MySQL table `scrapy_vagas` | deleted user state | Not migrated, by user decision (PRD › Data migration) | None; v2 starts empty |
| `README.md` | modified | Fully rewritten (FR-31) | Rewrite |
| `.gitignore` | modified | Add `.env`, `.venv`, `.ruff_cache`, coverage files; drop broken `../` lines | Edit |
| `pyproject.toml`, `.python-version` | new (draft exists) | Draft from the interrupted start lacks dependencies and import-linter/coverage config | Rewrite in task 1 per this spec |
| `src/take_jobs/` | new | Whole v2 package | Build per Build Order |
| `migrations/`, `alembic.ini` | new | Schema `0001` | Create |
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore` | new | Runtime | Create |
| `.github/workflows/ci.yml` | new | CI | Create |
| `tests/` | new | Suites per `_tests.md` | Create |
| git tag `v1` → `52018b3` | new | Comparison anchor (FR-32). That commit contains the leaked v1 MySQL password, which the user confirmed on 2026-10-30 is no longer used anywhere | Create locally; pushing it is the user's call. Never quote the password; cite file paths only |
| `uv.lock` | new | Required by `uv sync --frozen` in CI and in the Dockerfile | Generate with `uv lock` in task 1 and commit |
| `src/take_jobs/__main__.py` | new | Enables `python -m take_jobs`, which the scheduler and the spawned crawl child rely on | Create in task 1 (see Architectural Boundaries) |

No fallback, no compatibility shim and no placeholder for any v1 code path. No v1 module may be copied into `take_jobs`, even as dead code.

## Agent Manageability Plan

Operation is fully possible without a UI:
- `take-jobs collect [--trigger …] [--json]` has deterministic exit codes 0/1/2/3/4 and a structured JSON result.
- `GET /collection-runs[/{id}]` and `GET /health` report status and health.
- Every setting is an environment variable.
- Logs are `key=value` lines with a stable `event` field (see Monitoring).

All of it is consistent with `_dx.md`.

## Config Lifecycle

- **Source:** `take_jobs.config.Settings` (pydantic-settings, no prefix, environment then `.env`), with every key from `_dx.md` › Config and its default.
- **Lists:** `SCRAPE_TERMS` and the two `RELEVANCE_*` lists are comma-separated strings (annotated `NoDecode` with a `field_validator` that splits, strips and drops empties).
- **Validation, fail fast:**
  - `SCRAPE_TERMS` and `RELEVANCE_INCLUDE_KEYWORDS` must not be empty.
  - `SCRAPE_TERMS` must have distinct slugs: two different terms that normalize (rule 4) to the same words, such as `python`/`Python` or `desenvolvedor c#`/`desenvolvedor c++`, are rejected naming both, because both sites would get the same URL and the second combination could never run. A term with no letters or digits is rejected too. Repeating the exact same term is still accepted and collapses into one combination (review round 7, issue 002).
  - `SCRAPE_MAX_PAGES` ≥ 1; `SCRAPE_DOWNLOAD_DELAY` ≥ 1.0; `JOB_INACTIVE_AFTER_DAYS` ≥ 1; `SCRAPE_RUN_TIMEOUT_MINUTES` ≥ 20, so the crawl limit of rule 25 is at least 10 minutes.
  - `SCRAPE_CRON` must be a standard 5-field cron. Day-of-week follows standard cron (`0` and `7` = Sunday). `to_standard_crontab` expands the field into an explicit list of day names before `CronTrigger.from_crontab`, whose own numbering and name ranges start on Monday. `SCRAPE_TIMEZONE` must be a valid `ZoneInfo`.
  - `LOG_LEVEL` must be a stdlib level name.
- **Failure behavior:** the CLI exits `2` with `Invalid configuration: <KEY>: <reason>`; the API process fails at startup.
- **Compose:**
  - Every application key appears under `environment:` as `${KEY-default}`, without a colon, so the default applies only when the key is **unset**. An empty value set in `.env` reaches the application. That lets `RELEVANCE_EXCLUDE_KEYWORDS=` mean "no exclusions", and makes `SCRAPE_TERMS=` fail with exit `2` as US-003.EC-3 requires.
  - There is no `env_file:`. Compose reads the project's `.env`, when present, for interpolation, so no `.env` is needed.
  - `.env.example` is written by hand and kept in sync; IT-012 checks it against `Settings` and `docker-compose.yml`.

## Testing Approach

Every concrete case lives in [`_tests.md`](_tests.md).

- **Stack:** pytest, pytest-asyncio (session loop), httpx `AsyncClient` with `ASGITransport`, testcontainers PostgreSQL 17, pytest-cov.
- **Fakes at I/O boundaries only:** in-memory `JobRepository`, `CollectionRunRepository`, `UnitOfWork`, a fixed `Clock`, and a canned `JobScraper`.
- **Unit:**
  - Domain rules: normalization, relevance, seniority, activity, run status.
  - Application services with fakes.
  - Parsers against HTML fixtures stored in `tests/fixtures/html/`, trimmed live pages captured on 2026-10-30.
  - Spiders' paging and stop logic through Scrapy `HtmlResponse` objects built from fixtures.
  - API routes with dependency overrides.
  - Config validation.
- **Integration:** the real PostgreSQL container with Alembic migrations applied once per session. Covers:
  - the repositories: upsert semantics, search, indexes used, the single-running constraint, totals;
  - `CollectionService` with the real database and a fake scraper, including ingest failure;
  - the CLI `collect` exit codes, including a SIGTERM during the crawl;
  - the O5 query;
  - a performance check against 50k seeded jobs.
- **E2E:** **synchronous** tests that call `main([...], deps=build_cli_deps(settings, with_base_url(SOURCES, fixture_server_url)))` and query `create_app(settings, sources)` through `fastapi.testclient.TestClient`. The real composition and the real database are used, and the crawl runs in its spawned child, so `collect` can run many times per session. No test reaches the real sites (FR-30).
- **Static contract tests:** parse `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example` and the README, and check the `v1` tag and the artifact files. These are cheap automated owners for FR-27 and FR-29–FR-33 (O1).
- **Network guard:** `pytest-socket` blocks all sockets except loopback, the testcontainers host and the Docker unix socket (`--allow-hosts`, `--allow-unix-socket`). The spawned crawl child does not inherit it. Tests therefore pass `ScrapyJobScraper(child_initializer=install_test_socket_guard)`. That is a top-level function, with an optional `allow_hosts` argument (bound with `functools.partial` when needed), which installs the same guard inside the child:
  - It calls pytest-socket's `socket_allow_hosts(...)`, which patches `socket.socket.connect`.
  - It **also** wraps `socket.socket.connect_ex` with the same allow-list check, raising `SocketConnectBlockedError`. Twisted's TCP client connects with `connect_ex`, which pytest-socket does not patch (review round 3, reopened issue 010).

  Together with the URL-resolution rule (Integration Points), FR-30 is enforced where the scraping requests are actually made, and UT-116 proves it with a real Scrapy request.
- **CI:**
  - `actions/checkout` with `fetch-depth: 0` (tags available).
  - `uv sync --frozen`, `ruff format --check`, `ruff check`, `lint-imports`.
  - `pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80`.
  - Docker is available on `ubuntu-latest` runners for testcontainers.

## Development Sequencing

### Build Order

1. **Foundation:**
   - `pyproject.toml` with dependencies, the ruff config, import-linter contracts and pytest/coverage/pytest-socket config; `uv.lock` committed.
   - `.gitignore`, the package skeleton with `take_jobs/__main__.py`, and the `Settings` class.
   - Gate: `ruff`, `lint-imports` and an empty `pytest` run all pass.
2. **Domain:** models, ports, errors, rules. Gate: unit tests for the rules.
3. **Persistence:**
   - SQLAlchemy models, Alembic `0001`, repositories, UoW, the probe.
   - A Compose `db` service.
   - Gate: repository integration tests.
4. **Scraping:**
   - Fixtures, then the vagas.com parser and spider, then the Infojobs parser and spider.
   - Registry and `ScrapyJobScraper`.
   - Gate: parser and spider unit tests, plus an IT that runs the scraper's spawned-child crawl twice in one process on fixtures (R1).
5. **Application:** query services and `CollectionService`. Gate: unit tests with fakes, then an IT with the real database.
6. **CLI `collect`.** Gate: exit-code ITs.
7. **API:** app factory, schemas, routers, error handlers, health. Gate: API unit tests and E2E.
8. **Scheduler:** `take-jobs scheduler`, the startup run (rule 14), the probe retry, SIGTERM forwarding. Gate: unit tests with a fake runner and clock.
9. **Packaging:**
   - Dockerfile, the full Compose file, `.env.example`.
   - Gate: a manual `docker compose up --build` smoke test (O4).
10. **Delivery evidence:** CI workflow, README, `v1` tag. Gate: CI green.

Slices for `_tasks.md` follow user value. **Slice 1** takes the vagas.com path through steps 1–7 with only `q` and pagination, plus a minimal Compose file. Later slices extend it: Infojobs; relevance and seniority; lifecycle and filters; run history API; scheduler and startup run; packaging polish, CI, README and tag.

### Technical Dependencies

- Docker (local and CI) for PostgreSQL 17 and testcontainers.
- PostgreSQL contrib extensions `unaccent` and `pg_trgm`, both included in the official `postgres:17` image.
- Python 3.13, installed through uv.
- One-time network access to vagas.com and Infojobs to capture fixtures (task 3). Not needed afterwards.

## Monitoring and Observability

- **Logging:** stdlib `logging` with a `key=value` formatter on stdout, one line per event, and a stable `event` field. Events:
  - `scheduler_started`, `startup_collection`, `startup_collection_skipped`, `collection_triggered`.
  - `run_started`, `run_interrupted_marked_failed`.
  - `combination_finished` (`source`, `term`, `status`, `pages`, `new`, `seen_again`, `discarded`, `error`).
  - `run_finished` (`run_id`, `status`, `duration_s`, totals), `run_failed`.
  - `api_unhandled_error`.
  - Scrapy's own logging is set to `WARNING` unless `LOG_LEVEL=DEBUG`.
- **Metrics:** the run history is the metric store. O5 (≥ 95% successful combinations over 7 days) uses this pinned query, which the README documents and IT-014 tests:
  - The denominator is each finished run's `expected_combinations`, so whole-run failures (crash, ingest failure, signal, interruption) count fully as failures.
  - The window is the **7 complete days ending yesterday** (in `:tz`). Today is excluded, so the result does not depend on whether today's run has finished yet (review round 2, issue 002).
  - A day in the window with no finished run counts `:expected` combinations, all failed. `:expected` is the current sources × terms.

  ```sql
  WITH days AS (
    SELECT generate_series((now() AT TIME ZONE :tz)::date - 7, (now() AT TIME ZONE :tz)::date - 1, interval '1 day')::date AS day
  ), runs AS (
    SELECT (c.started_at AT TIME ZONE :tz)::date AS day,
           c.expected_combinations AS expected,
           (SELECT count(*) FROM collection_run_results r
             WHERE r.run_id = c.id AND r.status = 'success') AS ok
    FROM collection_runs c
    WHERE c.status <> 'running'
  )
  SELECT round(100.0 * coalesce(sum(r.ok), 0) / sum(coalesce(r.expected, :expected)), 1) AS success_rate_pct
  FROM days d LEFT JOIN runs r ON r.day = d.day;
  ```
- **Alerting:** none (local/self-hosted portfolio). Failures are visible through `GET /collection-runs` and the CLI exit codes.

## Technical Considerations

### Key Decisions

- **Activity computed at read time** (rule 9), rather than a stored `active` flag updated by the collector. It needs no extra write path or job, reactivation is automatic, and the threshold change of US-010.AC-5 applies immediately. Cost: an extra predicate on the recency index.
- **Single-running-run guard as a partial unique index**, rather than a PostgreSQL advisory lock. Collection crosses three separate event loops and a blocking crawl, so no single connection can hold a session lock for the whole run. The row-level guard survives that, and also records the run.
- **Per-combination results in a side table (`collection_run_results`), not a JSON/JSONB column on `collection_runs`.**
  - Results are queried relationally: O5's success rate across 7 days is a plain `GROUP BY` over `status`.
  - The side table enforces `unique (run_id, source, term)` and non-negative counts with constraints.
  - Results map 1:1 to the `CombinationResult` domain type.
  - A JSONB column would be simpler to write once, but it would push validation into application code, and the O5 query would need `jsonb_array_elements`.
  - The cost is one extra table and a join on the detail endpoint only; list views read totals with an aggregate subquery.
- **Results recorded at completion** instead of streamed per combination. One transaction per run completion keeps `totals` and `results` consistent; a `running` run shows `results: []`.
- **`published_label` stored as displayed.** The sites use relative or partial formats ("Hoje", "28 out"); parsing them adds no value to any FR. Recency comes from `first_seen_at` and `last_seen_at`.
- **No API version prefix.** There is one consumer and a single API version; adding `/v1` would be speculative.
- **`size` max 100 and `q` max 100 characters.** These bound the cost of a query (O7).

Consequential decisions with alternatives have ADRs (see the last section).

### Known Risks

| ID | Risk | Likelihood | Mitigation |
| --- | --- | --- | --- |
| R1 | The Twisted reactor cannot restart, and it can conflict with the `asyncio.run` calls around the crawl | Medium (confirmed in review round 1) | The crawl runs in a `spawn` child process with `TWISTED_REACTOR=None`, and the parent never starts a reactor. IT-007 runs two full collects in one process on fixtures |
| R6 | The `spawn` child must re-import the package, and pickling the report or registry fails | Low | `SourceDefinition.spider` and every report type are top-level importable classes. IT-007 covers the round trip |
| R2 | Slug rules for some terms (e.g. `.net`, `full stack`) do not match the sites' URL scheme | Medium | Task 3 checks every default term against the live sites once and records the outcome in the task memory. A mismatch becomes a per-source slug function; the product behavior is unchanged |
| R3 | Sites change their HTML or block the bot | Medium (over months) | Parsers are isolated and fixture-tested. Failures show up per combination in the run history. OQ-1 covers the User-Agent |
| R4 | Infojobs or vagas.com rate-limit even at 1 req/s | Low | Retries come from Scrapy defaults only. A failed combination is recorded and the run continues (rule 12) |
| R5 | One full run takes longer than 15 minutes on a slow network, missing O4 | Low | Total requests are bounded (≈ 480). The README notes that `SCRAPE_MAX_PAGES` can be lowered for a faster first look |

## Safety Invariants

1. At most one `collection_runs` row has `status = 'running'`. This is enforced by `uq_collection_runs_single_running`, not by application code alone.
2. A run leaves `running` exactly once, through `finish`, `fail_run` or `mark_interrupted`. Each of these is a conditional `UPDATE … WHERE id = :id AND status = 'running'`. An update that affects 0 rows raises `RunTakenOverError`, which the CLI reports with exit `1`.
3. `complete_run` writes all upserts, all `collection_run_results` rows and the final run status in **one transaction**. When it raises, the transaction is rolled back and `fail_run` records `ingest failed: …` in a **fresh** transaction (rule 26). Only SIGKILL or a host crash can leave the run `running`, and no orphan result rows exist in any case.
4. At most one job exists per (`source`, `external_id`) (unique constraint). `first_seen_at` is never part of the upsert's `SET` list.
5. The crawl runs in a `spawn` child process and never shares an event loop, a reactor or a database connection with the parent. The parent never starts a Twisted reactor. The parent reads the report from the pipe **before** joining the child, and closes its copy of the child's end of the pipe, so neither a report of any size nor a crash without a report can hang it (review round 2, issue 001). Each `asyncio.run` in the parent creates and disposes its own engine (`CliDeps.open_collection_service`).
6. No scraper or scheduler code path builds a shell command. The scheduler starts the collector with `subprocess.Popen([sys.executable, "-m", "take_jobs", "collect", "--trigger", <enum value>], shell=False)` and keeps the handle, so it can forward SIGTERM (ADR-004).
7. Per site, requests are serialized with at least `SCRAPE_DOWNLOAD_DELAY` between them. The settings are `CONCURRENT_REQUESTS_PER_DOMAIN=1`, `DOWNLOAD_DELAY=SCRAPE_DOWNLOAD_DELAY`, `RANDOMIZE_DOWNLOAD_DELAY=False` and `AUTOTHROTTLE_ENABLED=False`, with one spider per site (ADR-003). Only one crawl can be live at a time, because of invariant 1 together with invariant 9.
8. A run that receives SIGTERM or SIGINT is never recorded `success`, and never stays `running`.
   - **Who handles the signal:** the collector is the only signal handler. It installs one `signal.signal` handler for the whole command, never `loop.add_signal_handler`, and checks the stop flag after each non-terminal phase; after a terminal phase a set flag is only logged (`signal_after_finish`). The crawl child ignores SIGINT and installs no Scrapy handlers. The scheduler installs its shutdown handler before the database probe and the startup run.
   - **During the crawl:** the collector stops the child within 5 s (SIGTERM, then SIGKILL).
   - **During ingestion:** it cancels the ingestion task, which rolls the transaction back.
   - **Then:** it records the run `failed` with `interrupted by signal` and exits `4`.
   - **Scheduler:** it forwards SIGTERM to its collector child and waits up to 25 seconds, within `stop_grace_period: 30s`. The collector needs at most about 10 s of that (rule 24).
9. A live crawl ends before its run can be taken over: `CLOSESPIDER_TIMEOUT = (SCRAPE_RUN_TIMEOUT_MINUTES − 10) × 60` and `DOWNLOAD_TIMEOUT = 30` (rule 25). Rule 13's takeover therefore only ever applies to a dead process.

## File References

### Repo Files

- [`docs/tasks/fastapi-refactor/_prd.md`](_prd.md) — source requirements FR-01–FR-33 and objectives O1–O7; every task traces to it.
- [`docs/tasks/fastapi-refactor/RUN_LOG-felipemateusdecarvalho-2026-10-30-16-21.md`](RUN_LOG-felipemateusdecarvalho-2026-10-30-16-21.md) — the user's recorded answers behind the Non-Goals, defaults and the no-migration decision.
- [`docs/tasks/fastapi-refactor/_user_stories.md`](_user_stories.md) — acceptance criteria and edge cases each task implements.
- [`docs/tasks/fastapi-refactor/_dx.md`](_dx.md) — exact CLI, HTTP, config and error contract; the E2E tests use it verbatim.
- [`docs/tasks/fastapi-refactor/_tests.md`](_tests.md) — test IDs assigned to tasks.
- `pyproject.toml`, `.python-version` — draft from the interrupted start; task 1 rewrites them.
- `.gitignore` — v1 file with broken `../` entries; task 1 edits it.
- `README.md` — v1 README; the source for the "v1 → v2" section, then rewritten.
- v1 code at tag `v1` (`52018b3`), cited by path for the "v1 → v2" section only:
  - `src/sync_app/controllers/jobs_controller.py`: shell injection and hard-coded local path.
  - `src/sync_app/app.py` and `src/sync_app/bots/takeJobs/takeJobs/pipelines.py`: committed credentials. Cite these paths only, never the value (User Experience › Credentials).
  - `src/sync_app/bots/takeJobs/takeJobs/spiders/infojobs.py`: hard-coded `vendedor` pagination and the endless loop.
  - `src/sync_app/models/jobs_models.py`: model and table drift.

### External References

Cited by concept; nothing is vendored in this repo:

- Live listing pages `https://www.vagas.com.br/vagas-de-python` and `https://www.infojobs.com.br/vagas-de-emprego-python.aspx?page=1`, inspected on 2026-10-30. They are the source of the field mapping, the 403-without-headers behavior and the page-past-the-end behavior. Task 3 stores trimmed copies as fixtures.

### Design and Analysis Sources

- None beyond the PRD and the RUN_LOG.

## Assumptions and Defaults

- Python 3.13; PostgreSQL 17 (`postgres:17` image); API on port 8000 inside and outside the container (`API_PORT`).
- All defaults are those in [`_dx.md` › Config](_dx.md#config).
- Timestamps are stored and returned in UTC. Date query parameters and the cron use `SCRAPE_TIMEZONE`.
- Job ids are database-generated integers. Site ids are only stored in `external_id` and are not exposed.
- `external_id` fits in 64 characters (today both sites use numeric ids of 7–8 digits). Longer ids are skipped (rule 27).
- Description is the listing summary only; it is not truncated by the system.
- A combination with 0 cards on its first page is a `success` with 0 jobs, not a failure (US-005.EC-4).
- The startup run counts as a regular run in the history.
- The `v1` tag is created locally; pushing tags or branches is left to the user.
- Docker Compose v2.20 or later, for `depends_on` with `condition: service_completed_successfully`. No `env_file:` is used.
- The spec was revised after review round 1 (`reviews-001/`, 17 issues, all accepted by the user on 2026-10-30).

## Architecture Decision Records

- [ADR-001: Layered package with import-linter enforced boundaries](adrs/adr-001.md) — one package, four layers, `Protocol` ports, boundaries checked in CI.
- [ADR-002: Collection as a three-phase process; Scrapy never touches the database](adrs/adr-002.md) — start run → crawl in a spawned child → async ingest, instead of a DB pipeline inside Scrapy. Revised after review round 1 (spawn child, mandatory `spider_error`, signals).
- [ADR-003: One spider per source walking all terms](adrs/adr-003.md) — guarantees the per-site rate limit, instead of one crawler per term.
- [ADR-004: APScheduler container launching the collector as a subprocess](adrs/adr-004.md) — instead of system cron/supercronic or Celery beat. Revised after review round 1 (24-hour catch-up at start-up, SIGTERM forwarding, standard day-of-week).
- [ADR-005: Accent-insensitive search with unaccent + pg_trgm generated column](adrs/adr-005.md) — instead of PostgreSQL full-text search or unindexed `ILIKE`.
