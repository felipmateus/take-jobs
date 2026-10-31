# Developer Experience: take-jobs v2

Public-surface contract for take-jobs v2. Companion to `_spec.md` (Part II serves this surface) and
`_tests.md` (E2E journeys use these exact invocations). Written as if the feature already shipped.

## Golden Path

```bash
git clone https://github.com/felipmateus/take-jobs.git
cd take-jobs
docker compose up --build
```

```text
[+] Running 4/4
 ✔ Container take-jobs-db-1         Healthy
 ✔ Container take-jobs-migrate-1    Exited (0)
 ✔ Container take-jobs-api-1        Started
 ✔ Container take-jobs-scheduler-1  Started
migrate-1    | INFO  [alembic.runtime.migration] Running upgrade  -> 0001, create jobs and collection runs
api-1        | INFO:     Uvicorn running on http://0.0.0.0:8000
scheduler-1  | level=INFO event=scheduler_started cron="0 6 * * *" timezone=America/Sao_Paulo next_run=2026-10-31T06:00:00-03:00
scheduler-1  | level=INFO event=startup_collection reason=empty_job_store
scheduler-1  | Collection run 1 started (trigger: startup)
...
scheduler-1  | Collection run 1 finished: success in 8m41s (new=1184, seen_again=203, discarded=391)
```

In another terminal, after the run finishes:

```bash
curl -s "http://localhost:8000/jobs?q=python&seniority=senior&size=1"
```

```json
{
  "items": [
    {
      "id": 812,
      "title": "Desenvolvedor Python Sênior",
      "company": "ISLA",
      "location": "Porto Alegre - RS",
      "description": "Responsabilidades: desenvolver APIs REST em Python e manter integrações com o ERP.",
      "published_label": "28 out",
      "source": "infojobs",
      "url": "https://www.infojobs.com.br/vaga-de-desenvolvedor-python-senior-em-rio-grande-do-sul__11911899.aspx",
      "seniority": "senior",
      "first_seen_at": "2026-10-30T19:12:44Z",
      "last_seen_at": "2026-10-30T19:12:44Z",
      "active": true
    }
  ],
  "total": 37,
  "page": 1,
  "size": 1,
  "pages": 37
}
```

Interactive docs: open `http://localhost:8000/docs`.

## CLI

The `take-jobs` command is installed in the application image. Inside Docker Compose, run it through the `scheduler` service.

### `take-jobs collect`

Runs one collection immediately for every registered source × configured term.

```bash
docker compose run --rm scheduler take-jobs collect
```

```text
Collection run 8 started (trigger: manual)
vagas     desenvolvedor              ok      pages=20  new=12   seen_again=748  discarded=40
vagas     desenvolvedor python       ok      pages=2   new=1    seen_again=42   discarded=0
infojobs  desenvolvedor .net         FAILED  pages=0   new=0    seen_again=0    discarded=0    error="HTTP 403 Forbidden"
...
Collection run 8 finished: partial in 7m58s (new=96, seen_again=1702, discarded=388)
```

Exit code: `0`.

Options:

| Option                                     | Effect                                                               |
| ------------------------------------------ | -------------------------------------------------------------------- |
| `--trigger {manual,scheduled,startup}`     | Trigger recorded on the run. Default `manual`; the scheduler passes the other values. |
| `--json`                                   | Print only the final run as JSON, in the `GET /collection-runs/{id}` shape. |

```bash
docker compose run --rm scheduler take-jobs collect --json
```

```json
{
  "id": 9,
  "trigger": "manual",
  "status": "success",
  "started_at": "2026-10-30T20:01:02Z",
  "finished_at": "2026-10-30T20:08:40Z",
  "error": null,
  "totals": {"new": 4, "seen_again": 1801, "discarded": 391},
  "results": [
    {"source": "vagas", "term": "desenvolvedor", "status": "success", "pages": 20, "new": 1, "seen_again": 759, "discarded": 40, "error": null}
  ]
}
```

(`results` truncated here; it always has one entry per source × term.)

Exit codes:

| Code | Meaning                                                    |
| ---- | ---------------------------------------------------------- |
| 0    | Run finished as `success` or `partial`                     |
| 1    | Run finished as `failed` (crawl crash, ingest failure, or every combination failed), the run was taken over by another process, or the database is unreachable |
| 2    | Invalid configuration; no run recorded                     |
| 3    | Another collection run is in progress; no run recorded     |
| 4    | Stopped by SIGTERM/SIGINT; the run is recorded `failed` with error `interrupted by signal` |

Stopping a collection (Ctrl+C, `docker compose stop`) is safe. The run is recorded as failed, and the next start can collect again.

### `take-jobs scheduler`

Long-running process (the `scheduler` service's command). It runs `take-jobs collect --trigger scheduled` on `SCRAPE_CRON` in `SCRAPE_TIMEZONE`. When `SCRAPE_ON_START=true`, it also runs `take-jobs collect --trigger startup` at start, if either:
- the job store is empty (`reason=empty_job_store`); or
- no collection run has finished with a start in the last 24 hours (`reason=no_recent_run`), e.g. the machine was off at 06:00.

```text
level=INFO event=scheduler_started cron="0 6 * * *" timezone=America/Sao_Paulo next_run=2026-10-31T06:00:00-03:00
level=INFO event=startup_collection_skipped reason=recent_run_exists last_run_started_at=2026-10-30T09:00:04Z
```

```text
level=WARNING event=startup_probe_failed attempt=1 error="connection refused"
level=INFO event=startup_collection reason=no_recent_run last_run_started_at=2026-10-28T09:00:02Z
```

On SIGTERM or SIGINT, it forwards SIGTERM to a running collection, waits up to 25 s, and exits `0`.

Exit codes:
- `2`: invalid configuration.
- `1`: the database is still unreachable after 60 s of retries at start.
- Otherwise it runs until stopped.

## HTTP API

Base URL `http://localhost:8000`. JSON only. No authentication. Timestamps are UTC ISO-8601. Dates in query parameters are `YYYY-MM-DD`, interpreted in `SCRAPE_TIMEZONE`.

### `GET /jobs`

Search jobs. Only active jobs (seen within `JOB_INACTIVE_AFTER_DAYS`) unless `include_inactive=true`.

| Parameter          | Type                                      | Default | Rules                                      |
| ------------------ | ----------------------------------------- | ------- | ------------------------------------------ |
| `q`                | string                                    | —       | ≤ 100 chars; title, company, description; case- and accent-insensitive; blank = absent |
| `source`           | `vagas` \| `infojobs` (repeatable)        | all     | registered source ids                      |
| `location`         | string                                    | —       | ≤ 100 chars; "contains", case- and accent-insensitive |
| `seniority`        | `intern` \| `junior` \| `mid` \| `senior` (repeatable) | all | —                                   |
| `seen_from`        | date                                      | —       | job last seen on or after this date        |
| `seen_to`          | date                                      | —       | job first seen on or before this date; ≥ `seen_from` |
| `include_inactive` | boolean                                   | `false` | —                                          |
| `page`             | integer                                   | `1`     | ≥ 1                                        |
| `size`             | integer                                   | `20`    | 1–100                                      |

`200 OK`: see the Golden Path. Order: `last_seen_at` desc, `first_seen_at` desc, `id` desc.

```bash
curl -s "http://localhost:8000/jobs?page=999"
```

```json
{"items": [], "total": 1184, "page": 999, "size": 20, "pages": 60}
```

`422` examples:

```bash
curl -s "http://localhost:8000/jobs?size=500"
```

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request parameters.",
    "details": [{"field": "size", "message": "Input should be less than or equal to 100"}]
  }
}
```

```bash
curl -s "http://localhost:8000/jobs?seen_from=2026-10-20&seen_to=2026-10-01"
```

```json
{
  "error": {
    "code": "invalid_period",
    "message": "seen_from (2026-10-20) must be on or before seen_to (2026-10-01).",
    "details": []
  }
}
```

### `GET /jobs/{job_id}`

```bash
curl -s http://localhost:8000/jobs/812
```

`200 OK`: one job object, same shape as an `items` entry above. Inactive jobs are returned with `"active": false`.

```bash
curl -s http://localhost:8000/jobs/999999
```

`404 Not Found`:

```json
{"error": {"code": "job_not_found", "message": "Job 999999 was not found.", "details": []}}
```

### `GET /collection-runs`

Query parameters: `page` (default `1`, ≥ 1), `size` (default `20`, 1–100). Order: `started_at` desc.

```bash
curl -s "http://localhost:8000/collection-runs?size=2"
```

```json
{
  "items": [
    {
      "id": 9,
      "trigger": "manual",
      "status": "success",
      "started_at": "2026-10-30T20:01:02Z",
      "finished_at": "2026-10-30T20:08:40Z",
      "error": null,
      "totals": {"new": 4, "seen_again": 1801, "discarded": 391}
    },
    {
      "id": 8,
      "trigger": "manual",
      "status": "partial",
      "started_at": "2026-10-30T19:40:11Z",
      "finished_at": "2026-10-30T19:48:09Z",
      "error": null,
      "totals": {"new": 96, "seen_again": 1702, "discarded": 388}
    }
  ],
  "total": 9,
  "page": 1,
  "size": 2,
  "pages": 5
}
```

A run in progress has `"status": "running"`, `"finished_at": null`, and zero `totals`.

### `GET /collection-runs/{run_id}`

`200 OK`: the run in the list shape plus `results` (see the `--json` example under CLI). A `running` run has `"results": []`.

```bash
curl -s http://localhost:8000/collection-runs/404
```

`404 Not Found`:

```json
{"error": {"code": "collection_run_not_found", "message": "Collection run 404 was not found.", "details": []}}
```

### `GET /health`

```bash
curl -s -i http://localhost:8000/health
```

```text
HTTP/1.1 200 OK
{"status": "ok", "database": "ok"}
```

With the database down: `HTTP/1.1 503 Service Unavailable` and `{"status": "unavailable", "database": "unreachable"}`.

### `GET /docs`, `GET /openapi.json`

Swagger UI and the OpenAPI 3 document for all routes above.

## Config

Every key is optional; Docker Compose and the application use these defaults. Copy `.env.example` to `.env` to override. A key set to an empty value in `.env` is passed through as empty, not replaced by the default. That is how `RELEVANCE_EXCLUDE_KEYWORDS=` disables exclusions. An empty required key, such as `SCRAPE_TERMS=`, is a configuration error.

```dotenv
# Port published on the host for the API.
API_PORT=8000

# PostgreSQL (development defaults; the database port is not published to the host).
POSTGRES_USER=take_jobs
POSTGRES_PASSWORD=take_jobs_dev
POSTGRES_DB=take_jobs
DATABASE_URL=postgresql+asyncpg://take_jobs:take_jobs_dev@db:5432/take_jobs

# Collection schedule (standard 5-field cron; day-of-week 0 or 7 = Sunday).
SCRAPE_CRON=0 6 * * *
SCRAPE_TIMEZONE=America/Sao_Paulo
SCRAPE_ON_START=true
SCRAPE_RUN_TIMEOUT_MINUTES=60

# What is collected (comma-separated).
SCRAPE_TERMS=desenvolvedor,programador,engenheiro de software,desenvolvedor backend,desenvolvedor frontend,desenvolvedor full stack,desenvolvedor mobile,desenvolvedor python,desenvolvedor java,desenvolvedor javascript,desenvolvedor .net,desenvolvedor php

# Scraping conduct.
SCRAPE_MAX_PAGES=20
SCRAPE_DOWNLOAD_DELAY=1.0
SCRAPE_USER_AGENT=take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)

# Relevance filter (comma-separated; case- and accent-insensitive whole words/phrases).
RELEVANCE_INCLUDE_KEYWORDS=desenvolvedor,desenvolvedora,developer,programador,programadora,programmer,engenheiro de software,engenheira de software,software engineer,dev,backend,back-end,frontend,front-end,full stack,fullstack,full-stack
RELEVANCE_EXCLUDE_KEYWORDS=cnc,torno,usinagem,producao,pcp,manutencao,negocios,vendas,comercial,textil,moda,costura

# Job lifecycle.
JOB_INACTIVE_AFTER_DAYS=7

LOG_LEVEL=INFO
```

| Key                          | Observable effect                                                              |
| ---------------------------- | ------------------------------------------------------------------------------ |
| `API_PORT`                   | Host port where the API answers.                                               |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credentials and name of the database container.       |
| `DATABASE_URL`               | Database the API, migrations and collector connect to.                         |
| `SCRAPE_CRON`                | Run time, as a standard 5-field cron. Day-of-week `0` and `7` are Sunday; names like `mon-fri` also work. |
| `SCRAPE_TIMEZONE`            | Time zone for `SCRAPE_CRON` and for date query parameters.                     |
| `SCRAPE_ON_START`            | Whether the scheduler collects immediately on start when the job store is empty or no run finished in the last 24 h. |
| `SCRAPE_RUN_TIMEOUT_MINUTES` | Run time budget (≥ 20). The crawl stops after this minus 10 minutes, and unfinished combinations fail with `run time limit reached`. A `running` run older than this belongs to a dead process and is marked `interrupted`. |
| `SCRAPE_TERMS`               | Search terms collected on every source; must not be empty or share a slug.     |
| `SCRAPE_MAX_PAGES`           | Max listing pages per source × term per run (≥ 1).                             |
| `SCRAPE_DOWNLOAD_DELAY`      | Min seconds between two requests to the same site (≥ 1.0).                     |
| `SCRAPE_USER_AGENT`          | User-Agent sent to the sites.                                                  |
| `RELEVANCE_INCLUDE_KEYWORDS` | A title must contain one of these to be stored; must not be empty.             |
| `RELEVANCE_EXCLUDE_KEYWORDS` | A title containing one of these is discarded; may be empty.                    |
| `JOB_INACTIVE_AFTER_DAYS`    | Days without being seen before a job is inactive (≥ 1).                        |
| `LOG_LEVEL`                  | Log verbosity of all services.                                                 |

## Errors

All HTTP errors share one shape: `{"error": {"code": str, "message": str, "details": [{"field": str, "message": str}]}}`.

| Condition                                 | Surface | Result                                                                    |
| ----------------------------------------- | ------- | ------------------------------------------------------------------------- |
| Invalid query/path parameter              | HTTP    | `422`, `validation_error`, one `details` entry per invalid field          |
| `seen_from` after `seen_to`               | HTTP    | `422`, `invalid_period`                                                   |
| Unknown job id                            | HTTP    | `404`, `job_not_found`                                                    |
| Unknown run id                            | HTTP    | `404`, `collection_run_not_found`                                         |
| Unknown route                             | HTTP    | `404`, `not_found`                                                        |
| Database unreachable during a request     | HTTP    | `503`, `database_unavailable`, message `The database is unavailable. Try again later.` |
| Unexpected failure                        | HTTP    | `500`, `internal_error`, message `An unexpected error occurred.` (details only in logs) |
| Invalid configuration                     | CLI     | exit `2`, `Invalid configuration: <KEY>: <reason>`                        |
| Another run in progress                   | CLI     | exit `3`, `Another collection run (id <N>) is in progress since <timestamp>.` |
| Database unreachable                      | CLI     | exit `1`, `Cannot connect to the database at <host>:<port>.`              |
| Ingestion failed                          | CLI     | exit `1`, `Collection run <N> failed: ingest failed: <ExceptionType>: <message>`; run `error` has the same text |
| Crawl process crashed                     | CLI     | exit `1`, `Collection run <N> failed: <crash message>`                     |
| Run taken over by another process         | CLI     | exit `1`, `Collection run <N> was taken over by another process; its results were discarded.` |
| SIGTERM / SIGINT during a run             | CLI     | exit `4`, `Collection run <N> interrupted by signal.`; run `failed`, error `interrupted by signal` |
| Combination: page could not be parsed     | Run history | result `failed`, error `parse error: <ExceptionType>: <message>`       |
| Combination: crawl time limit reached     | Run history | result `failed`, error `run time limit reached`                        |
| Scheduler: database unreachable at start  | Scheduler | `startup_probe_failed` per attempt; exit `1` after 60 s                 |
