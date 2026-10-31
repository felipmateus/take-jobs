# take-jobs

[![CI](https://github.com/felipmateus/take-jobs/actions/workflows/ci.yml/badge.svg)](https://github.com/felipmateus/take-jobs/actions/workflows/ci.yml)

A job bank for developers: it collects openings from vagas.com and Infojobs every day, keeps the relevant ones in PostgreSQL and serves them through a FastAPI HTTP API.

```bash
git clone https://github.com/felipmateus/take-jobs.git && cd take-jobs
docker compose up --build
```

When the stack is up, the first collection starts by itself. After a minute or so, open <http://localhost:8000/docs>, or run `curl "http://localhost:8000/jobs?q=python&size=5"`.

This is **v2**, a rebuild of the original Flask version (tag `v1`) with spec-driven development. See [v1 → v2](#v1--v2) for what changed and why, and [`docs/tasks/fastapi-refactor/`](docs/tasks/fastapi-refactor/) for the PRD, tech spec, ADRs, task files and review rounds.

## Overview

| Piece | What it does |
| --- | --- |
| `db` | PostgreSQL 17 (not published to the host). |
| `migrate` | Runs `alembic upgrade head` once and exits. |
| `api` | Read-only FastAPI app (`GET /jobs`, `GET /collection-runs`, `GET /health`, interactive docs at `/docs`). |
| `scheduler` | `take-jobs scheduler`: collects on a cron schedule and once at start when the store is empty or the last run is more than 24 hours old. |

The code is layered, and the dependency direction is enforced by `lint-imports` in CI:

```text
src/take_jobs/
  domain/          pure Python: models, ports, rules (relevance, seniority, run status, cron)
  application/     use cases: search jobs, list runs, collect
  infrastructure/  db (SQLAlchemy, Alembic, repositories) and scraping (Scrapy spiders, one per site)
  api/             FastAPI routers, schemas, error mapping
  cli/             `take-jobs collect` and `take-jobs scheduler`
  config.py        Settings read from the environment
```

Collection details:
- Every source is crawled for every configured search term (2 sources × 12 terms by default).
- A title must pass the relevance policy (include and exclude keywords) to be stored.
- Jobs are upserted by `(source, external_id)`, so running twice never duplicates.
- A job not seen for `JOB_INACTIVE_AFTER_DAYS` days is reported as `active: false`.
- Every run is recorded with one result per source and term, so a partial failure is visible.
- Only one run can be active at a time. The database enforces it, and stopping a run (Ctrl+C or `docker compose stop`) records it as failed.

Observed on a clean machine (macOS, Docker Desktop, empty database, no `.env`):
- `docker compose up --build -d` returned in 15 s with warm layers, and `GET /health` answered 200 about 21 s after the start.
- The first collection finished `success` in 33 s (100 new jobs, 24 of 24 combinations) and `GET /jobs` returned them about 51 s after the start. The target was 15 minutes.
- A second start with the same volume answered `/health` after about 10 s and skipped the startup collection (`startup_collection_skipped reason=recent_run_exists`).
- A random sample of 50 stored jobs had 48 genuine development roles (96%, target 90%). The two misses were "Programador" roles in logistics and visual communication.

## Running

Requirements: Docker with Compose v2. No `.env` file is needed.

```bash
docker compose up --build
```

- The API is on <http://localhost:8000>. Set `API_PORT` to publish another host port: `API_PORT=8001 docker compose up`.
- To lower the time of a first look, set `SCRAPE_MAX_PAGES` (default 20) in `.env`.
- Stop with Ctrl+C or `docker compose stop`. The data lives in the `pgdata` volume. Remove it with `docker compose down -v`.

Run a collection by hand (same options as the scheduler; `--json` prints only the final run):

```bash
docker compose run --rm scheduler take-jobs collect
docker compose run --rm scheduler take-jobs collect --json
```

Exit codes of `collect`: `0` success or partial, `1` failed (or database unreachable), `2` invalid configuration, `3` another run is active, `4` stopped by a signal.

Development (Python 3.13 and [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run ruff format --check && uv run ruff check && uv run lint-imports
uv run pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80
```

The integration and end-to-end tests start PostgreSQL 17 through testcontainers, so Docker must be running. No test reaches the real sites: sockets other than loopback and Docker are blocked by `pytest-socket`, including inside the crawl child process. CI runs the same commands on every push and pull request.

## Querying the API

Interactive docs: <http://localhost:8000/docs>. All responses are JSON, there is no authentication and no version prefix.

| Route | Purpose |
| --- | --- |
| `GET /jobs` | Search and filter jobs, paginated. |
| `GET /jobs/{job_id}` | One job. |
| `GET /collection-runs` | Run history, newest first. |
| `GET /collection-runs/{run_id}` | One run with its per source and term results. |
| `GET /health` | `200` when the database answers, `503` otherwise. |

`GET /jobs` parameters:

| Parameter | Meaning |
| --- | --- |
| `q` | Text in title, company or description (case and accent insensitive, up to 100 characters). |
| `source` | `vagas` or `infojobs` (repeatable). |
| `location` | "Contains", case and accent insensitive. |
| `seniority` | `intern`, `junior`, `mid` or `senior` (repeatable). |
| `seen_from`, `seen_to` | Dates (`YYYY-MM-DD`, in `SCRAPE_TIMEZONE`). |
| `include_inactive` | Also return jobs not seen recently (default `false`). |
| `page`, `size` | Pagination (`size` from 1 to 100, default 20). |

```bash
curl -s "http://localhost:8000/jobs?q=python&seniority=senior&source=infojobs&size=1"
curl -s "http://localhost:8000/collection-runs?size=5"
curl -s "http://localhost:8000/collection-runs/1"
```

Errors share one shape, `{"error": {"code", "message", "details"}}`, with codes such as `validation_error`, `job_not_found` and `database_unavailable`.

Search latency was measured at p95 below 300 ms on 50,000 jobs, including 1 and 2 character queries (IT-011; measured 47-50 ms for 3 or more characters and 70-83 ms for 1 or 2 characters on a laptop).

### Collection success rate (O5)

The run history is the metric store. The query below reports the percentage of successful source and term combinations over the last 7 complete days (today excluded). Whole-run failures count fully, because the denominator is each run's `expected_combinations`, and a day with no finished run counts `:expected` combinations, all failed. Bind `:tz` to `SCRAPE_TIMEZONE` and `:expected` to sources × terms (24 by default). The target is at least 95% after 7 days of operation (it needs real operation, so it is checked after delivery). IT-014 tests this exact statement (it lives in `src/take_jobs/infrastructure/db/metrics.sql`).

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

To run it against the Compose database with `psql`, substitute the two parameters:

```bash
sed -e "s/:tz/'America\/Sao_Paulo'/g" -e "s/:expected/24/g" src/take_jobs/infrastructure/db/metrics.sql \
  | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## Configuration

Everything is configured through environment variables, and every key is optional. Copy [`.env.example`](.env.example) to `.env` to override them: Compose reads `.env` from the project directory, and the file documents every key with its default.

- A key set to an empty value is passed through as empty and is **not** replaced by the default. For example, `RELEVANCE_EXCLUDE_KEYWORDS=` disables the exclude list.
- An invalid value stops the process with exit code `2` and a message that names the key.
- `.env.example` is checked against the `Settings` class and `docker-compose.yml` by the test suite, so the three cannot drift.

| Key | Default | Purpose |
| --- | --- | --- |
| `API_PORT` | `8000` | Host port published for the API. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `take_jobs`, `take_jobs_dev`, `take_jobs` | Credentials and name of the database the `db` service creates (development defaults). |
| `DATABASE_URL` | `postgresql+asyncpg://take_jobs:take_jobs_dev@db:5432/take_jobs` | Database the API, the migrations and the collector connect to. |
| `SCRAPE_CRON` | `0 6 * * *` | Collection schedule (5-field cron). |
| `SCRAPE_TIMEZONE` | `America/Sao_Paulo` | Time zone of the schedule and of date parameters. |
| `SCRAPE_ON_START` | `true` | Collect at start when the store is empty or no run finished in the last 24 hours. |
| `SCRAPE_RUN_TIMEOUT_MINUTES` | `60` | Run budget (at least 20); the crawl stops 10 minutes before it. |
| `SCRAPE_TERMS` | 12 developer terms | Search terms (comma-separated). Terms that differ only in case, accents or punctuation (`c#` and `c++`) are rejected. |
| `SCRAPE_MAX_PAGES` | `20` | Listing pages per source and term. |
| `SCRAPE_DOWNLOAD_DELAY` | `1.0` | Seconds between requests to the same site (at least 1.0). |
| `SCRAPE_USER_AGENT` | `take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)` | Honest User-Agent sent to the sites. |
| `RELEVANCE_INCLUDE_KEYWORDS`, `RELEVANCE_EXCLUDE_KEYWORDS` | see `.env.example` | A title needs one include keyword and no exclude keyword. |
| `JOB_INACTIVE_AFTER_DAYS` | `7` | Days unseen before a job is inactive. |
| `LOG_LEVEL` | `INFO` | Log level of all services. |

**`DATABASE_URL` and `POSTGRES_*` are coupled.** `docker-compose.yml` passes `POSTGRES_*` to the `db` service and `DATABASE_URL` to the application services, but it does not build one from the other, so that every default equals `.env.example`. If you change `POSTGRES_USER`, `POSTGRES_PASSWORD` or `POSTGRES_DB` in `.env`, change `DATABASE_URL` to match. The development password is only meant for local use: set your own value in `.env` for anything exposed to a network.

## v1 → v2

v1 (tag `v1`, commit `52018b3`) was a Flask app that scraped on demand and streamed items over a WebSocket. v2 is a rebuild from a PRD and a tech spec (`docs/tasks/fastapi-refactor/`). Compare the two with `git diff v1 HEAD --stat`, or browse v1 with `git show v1:src/sync_app/app.py`.

| v1 problem (file) | v2 fix |
| --- | --- |
| The MySQL password is committed in plain text, in the source (`src/sync_app/app.py`, `src/sync_app/bots/takeJobs/takeJobs/pipelines.py`). It is still in the git history. | No secret in the repository. Settings come from the environment, `.env.example` holds development-only defaults, `.env` is ignored, and a test scans every tracked and untracked file for credentials (IT-012). **If you ever ran v1, treat that password as leaked and rotate it.** |
| A `GET /jobs/<search>/` request starts two `scrapy crawl` processes through `subprocess.Popen(..., shell=True)` with the URL segment pasted into the command line (`src/sync_app/controllers/jobs_controller.py`). That is a shell injection and an unbounded, unauthenticated way to start crawls. | The API is read-only. Collection runs only from the scheduler or `take-jobs collect`, with terms from configuration. Subprocess arguments are never built from user input, and the database allows a single running run. |
| An absolute path of the author's laptop and `host.docker.internal` are hard coded (`src/sync_app/controllers/jobs_controller.py`, `src/sync_app/app.py`). The app only ran on one machine. | `docker compose up --build` is the whole setup: database, migrations, API and scheduler, with healthchecks and no host path. |
| Scraped items travel through a separate WebSocket relay (`src/async_app/app.py`) that broadcasts every message to every client and is fed by the Scrapy pipeline (`src/sync_app/bots/takeJobs/takeJobs/pipelines.py`). | No relay. Items are stored in PostgreSQL and read through the API. Run history shows what happened. |
| The pipeline opens a MySQL connection per process, creates its own table and deduplicates by title alone: an in-memory set plus a `select ... where title = %s` (`src/sync_app/bots/takeJobs/takeJobs/pipelines.py`). Two different companies with the same title collapse into one job, and a job still listed is never marked as seen again. | Alembic migration `0001`, and an upsert by `(source, external_id)` that inserts new jobs, refreshes `last_seen_at` for the others and counts both. |
| The model stores dates as strings and truncates descriptions to 80 characters. It searches with `lower(title) LIKE`, so it cannot use an index (`src/sync_app/models/jobs_models.py`). | Typed columns (`timestamptz`), a computed activity flag, and trigram indexes on unaccented text. p95 below 300 ms on 50,000 jobs (IT-011). |
| The query endpoint has no validation or error contract, and `limit` has no upper bound (`src/sync_app/controllers/jobs_controller.py`). | Validated parameters (`size` up to 100), typed responses, one error shape, OpenAPI docs. |
| Scrapers collect everything the site returns, regardless of relevance (`src/sync_app/bots/takeJobs/takeJobs/spiders/vagas.py`, `.../infojobs.py`). | A relevance policy (include and exclude keywords, whole-word matching) stored with seniority. In a sample of 50 stored jobs, 48 were development roles. |
| `debug=True`, `TESTING=True` and `SQLALCHEMY_ECHO` are on in the app itself, and scraping prints with `print` (`src/sync_app/app.py`, `.../spiders/vagas.py`). | Structured `key=value` logs with one `LOG_LEVEL`, and a health endpoint. |
| About 100 packages pinned by `pip freeze`, including unrelated ones such as `pandas`, `numpy` and `pipenv`, on `python:3.10.6` as root (`src/sync_app/requirements.txt`, `src/sync_app/Dockerfile`). | `pyproject.toml` and a committed `uv.lock` with a few direct dependencies, `python:3.13-slim` and a non-root user (`Dockerfile`). |
| Two apps, MVC folders mixed with the crawler, and runtime artifacts committed (`src/sync_app/bots/takeJobs/teste.json`, `src/sync_app/bots/takeJobs/.jobs.json.icloud`). | One package in layers (`domain`, `application`, `infrastructure`, `api`, `cli`), with the boundaries checked by `lint-imports`. |
| No tests and no CI anywhere in v1. | About 400 tests (unit, integration on a real PostgreSQL, end to end) and a CI workflow (`.github/workflows/ci.yml`) running format, lint, `lint-imports` and `pytest` with an 80% coverage gate on the domain and application layers. |

### Evidence

- Tag: `git rev-parse v1^{commit}` prints `52018b3...`.
- The design trail is in `docs/tasks/fastapi-refactor/`: `_prd.md`, `_spec.md`, `_user_stories.md`, `_dx.md`, `_tests.md`, `_tasks.md`, `adrs/`, `reviews-*/` and `memory/`.
- CI: the badge at the top links to the workflow runs.
- O5 (at least 95% of combinations successful over 7 days): run the [query above](#collection-success-rate-o5) after a week of operation and record the result here. Not measured yet.
