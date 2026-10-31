# User Stories: take-jobs v2

Canonical behavior catalog for the take-jobs v2 refactor. Companion to `_spec.md`; consumed by
`_spec.md` Part II (component mapping) and `_tests.md` (coverage matrix). Derived from
[`_prd.md`](_prd.md); the `FR-NN` references point to its functional requirements.

## Personas

- **Technical evaluator** — a recruiter, interviewer or engineer assessing the author's work. Limited time; wants to run the project with one command, explore the API without reading code, and see evidence of process (SDD artifacts, CI) and of the evolution from v1.
- **API consumer** — the author, querying the job bank to follow developer openings. Wants relevant, current jobs that are easy to search and filter.
- **Maintainer** — the author operating the system: tuning configuration, running collections on demand, checking whether collections worked, and adding job boards later.

## Story Index

| ID     | Feature Area         | Persona             | Story                                                       |
| ------ | -------------------- | ------------------- | ----------------------------------------------------------- |
| US-001 | Collection           | API consumer        | Job bank refreshed daily from vagas.com and Infojobs        |
| US-002 | Collection           | API consumer        | Each job stored once, with first and last seen dates        |
| US-003 | Collection           | Maintainer          | Run a collection on demand                                  |
| US-004 | Collection           | Technical evaluator | Real jobs available right after the first start             |
| US-005 | Collection           | Maintainer          | One failing site or term does not stop the others           |
| US-006 | Collection           | Maintainer          | Collection is polite and bounded                            |
| US-007 | Collection           | Maintainer          | Add a job board without changing the API                    |
| US-008 | Relevance            | API consumer        | Only software development jobs are stored                   |
| US-009 | Relevance            | API consumer        | Seniority derived from the job title                        |
| US-010 | Lifecycle            | API consumer        | Only active jobs by default; stale jobs become inactive     |
| US-011 | Search API           | API consumer        | Text search across title, company and description           |
| US-012 | Search API           | API consumer        | Filter by source, location, seniority and seen period       |
| US-013 | Search API           | API consumer        | Paginated results, most recent first                        |
| US-014 | Search API           | API consumer        | Get a single job by id                                      |
| US-015 | Search API           | Technical evaluator | Interactive API documentation                               |
| US-016 | Operations           | Maintainer          | Health check reports service and database status            |
| US-017 | Run history          | Maintainer          | List collection runs                                        |
| US-018 | Run history          | Maintainer          | Inspect one run's per-site, per-term results                |
| US-019 | Developer experience | Technical evaluator | Start the whole system with one command                     |
| US-020 | Developer experience | Maintainer          | Configure everything through environment variables          |
| US-021 | Developer experience | Technical evaluator | CI runs lint and tests on every change                      |
| US-022 | Developer experience | Technical evaluator | Compare v1 and v2 and read the SDD artifacts                |

## Collection

### US-001: Daily collection

**As an** API consumer, **I want** the job bank refreshed once a day from vagas.com and Infojobs for every configured developer search term, **so that** I always query recent openings without searching each site myself. (FR-01, FR-02, FR-03, FR-04)

Acceptance criteria:

- AC-1: Given the system is running with default configuration, when the clock reaches 06:00 in `America/Sao_Paulo`, then a collection run starts with trigger `scheduled`.
- AC-2: Given `SCRAPE_CRON` and `SCRAPE_TIMEZONE` are changed, when the scheduler restarts, then the next run starts at the new time in the new time zone.
- AC-3: Given a run completes, when I list runs, then it has one result per source × term combination: 2 sources × the configured terms (24 with the default 12 terms).
- AC-4: Given a run collected a job, when I fetch it from the API, then it has title, company, location, description, publication date as displayed by the site, source, original URL, first-seen and last-seen timestamps.

Edge cases:

- EC-1: A listing card has no title or no site identifier → the card is skipped and the combination still succeeds.
- EC-2: A listing card has no company, location, description or publication date → the job is stored with those fields as `null`.
- EC-3: A scheduled time is missed because the scheduler (or the machine) was down → the cron does not replay it. When the scheduler starts again and no run has finished with a start in the last 24 hours, it collects immediately with trigger `startup` (US-004.AC-4). Revised after review round 1, issue 004.
- EC-4: The scheduled time arrives while another run is still in progress → no second run is started (see US-003.EC-1).

### US-002: Deduplication

**As an** API consumer, **I want** each job stored once even when several terms or days return it, **so that** search results have no duplicates and I can tell how long a job has been listed. (FR-05)

Acceptance criteria:

- AC-1: Given a job is collected for the first time, when the run finishes, then it exists once with `first_seen_at` equal to `last_seen_at`.
- AC-2: Given a stored job is collected again in a later run, when that run finishes, then `last_seen_at` is updated, `first_seen_at` is unchanged, and there is still one record.
- AC-3: Given a stored job is collected again with a changed title, company, location, description or publication date, when that run finishes, then the stored fields reflect the latest values.

Edge cases:

- EC-1: The same job is returned for two terms in the same run → it is stored once; the first combination to collect it counts it as `new`, the other as `seen_again`.
- EC-2: Two different sites list the same opening → they are two jobs, because identity is per source.

### US-003: On-demand collection

**As a** maintainer, **I want** a documented command that runs a collection immediately, **so that** I can refresh data or test configuration without waiting for the schedule. (FR-07)

Acceptance criteria:

- AC-1: Given the system is running, when I run `docker compose run --rm scheduler take-jobs collect`, then a run with trigger `manual` executes and the command prints one line per combination and a final summary.
- AC-2: Given the run ends as `success` or `partial`, when the command exits, then the exit code is `0`; when it ends as `failed`, the exit code is `1`; when it was stopped by a signal, the exit code is `4`.
- AC-3: Given I pass `--json`, when the command finishes, then it prints only the run summary as JSON in the shape returned by `GET /collection-runs/{id}`.

Edge cases:

- EC-1: Another run is in progress → the command exits with code `3` and the message `Another collection run (id <N>) is in progress since <timestamp>.`, and no new run is recorded.
- EC-2: A run has been `running` for longer than `SCRAPE_RUN_TIMEOUT_MINUTES` (default 60; the process died, e.g. SIGKILL) → it is marked `failed` with error `interrupted`, and the new run proceeds.
- EC-3: The configuration is invalid (e.g. empty `SCRAPE_TERMS`, including `SCRAPE_TERMS=` in `.env` under Docker Compose) → the command exits with code `2` and names the invalid variable; no run is recorded.
- EC-4: The database is unreachable → the command exits with code `1` and a message naming the database; no run is recorded.
- EC-5: I press Ctrl+C, or the container receives SIGTERM, during the crawl or ingestion → the crawl stops, nothing from the run is stored, the run is recorded `failed` with error `interrupted by signal`, and the command exits `4`. A following `collect` starts immediately (no `3`).
- EC-6: Storing the collected jobs fails (database error) → no job from the run is stored, the run is recorded `failed` with error `ingest failed: <ExceptionType>: <message>`, and the command exits `1`.
- EC-7: My run was taken over by another process (rule 13) by the time it finishes → its results are discarded, and the command exits `1` with `Collection run <N> was taken over by another process; its results were discarded.`

### US-004: Initial collection

**As a** technical evaluator, **I want** the system to collect jobs immediately on its first start, and whenever it starts after missing a day, **so that** the API has real, recent data within minutes. (FR-06, extended after review round 1, issue 004)

Acceptance criteria:

- AC-1: Given the jobs store is empty and `SCRAPE_ON_START=true`, when the scheduler starts, then a run with trigger `startup` begins immediately (`reason=empty_job_store`).
- AC-2: Given the jobs store has jobs and a run finished with a start less than 24 hours ago, when the scheduler starts, then no immediate run starts; it waits for the schedule.
- AC-3: Given `SCRAPE_ON_START=false`, when the scheduler starts with an empty store, then no immediate run starts.
- AC-4: Given the jobs store has jobs but the latest finished run started more than 24 hours ago (or no run ever finished), when the scheduler starts, then a run with trigger `startup` begins immediately (`reason=no_recent_run`).

Edge cases:

- EC-1: The startup run collects zero relevant jobs → the next scheduler restart triggers another startup run, since the store is still empty.
- EC-2: The stack is stopped (Ctrl+C or `docker compose down`) while the startup run is in progress → the scheduler forwards SIGTERM, and the run is recorded `failed` with `interrupted by signal`. On the next `docker compose up`, the store is still empty, so a new startup run begins immediately and is not blocked by the stopped run. Revised after review round 1, issue 003.
- EC-3: The database is not reachable yet when the scheduler starts → it retries for up to 60 seconds (`startup_probe_failed` logged per attempt), then exits `1` and is restarted by Compose. The startup run happens once the database is reachable.

### US-005: Partial failure isolation

**As a** maintainer, **I want** a failure in one site × term combination to leave the others unaffected, **so that** one broken site does not cost a whole day of data. (FR-09)

Acceptance criteria:

- AC-1: Given one combination fails and the others succeed, when the run finishes, then the run status is `partial`, the failed combination has status `failed` and an error message, and jobs from the other combinations are stored.
- AC-2: Given every combination fails, when the run finishes, then the run status is `failed`.
- AC-3: Given a combination failed today, when nothing else happens, then it is not retried until the next scheduled run.

Edge cases:

- EC-1: A combination fails after some pages succeeded → jobs from the successful pages are stored; the combination is `failed` with the pages count reached.
- EC-2: A site returns HTTP 403 or 5xx after the built-in request retries → that combination fails with an error naming the status code.
- EC-3: A request is disallowed by robots.txt → that combination fails with error `blocked by robots.txt`.
- EC-4: The site's HTML changed and the first page yields no cards → the combination succeeds with 0 jobs. A zero-job pattern across all terms of one source is visible in the run history.
- EC-5: The crawl process crashes as a whole → the run is marked `failed` with the error message, and no partial ingestion happens for that run.
- EC-6: A listing page cannot be parsed (an exception in the parser, e.g. after a site HTML change) → that combination fails with `parse error: <ExceptionType>: <message>`; jobs from its earlier pages are kept, and other combinations continue. It is never recorded as `success`.
- EC-7: The crawl reaches its time limit (`SCRAPE_RUN_TIMEOUT_MINUTES` − 10) → combinations that had not finished fail with `run time limit reached`; jobs collected so far are stored; the run is `partial` or `failed`.

### US-006: Polite, bounded collection

**As a** maintainer, **I want** collection to respect robots.txt, rate limits and page limits and to stop at the end of the results, **so that** the project scrapes responsibly and runs never loop. (FR-08; PRD scraping conduct)

Acceptance criteria:

- AC-1: Given default configuration, when a run executes, then requests to a single site are at least `SCRAPE_DOWNLOAD_DELAY` = 1.0 seconds apart.
- AC-2: Given a term has more result pages than `SCRAPE_MAX_PAGES` = 20, when it is collected, then exactly 20 listing pages are requested for it.
- AC-3: Given a listing page brings no job not already seen for that term in this run, when it is parsed, then no further page is requested for that term.
- AC-4: Given vagas.com shows no "more jobs" link, when the page is parsed, then no further page is requested for that term.

Edge cases:

- EC-1: Infojobs is asked for a page past the end and returns page 1 again → collection for that term stops after that page (AC-3).
- EC-2: `SCRAPE_MAX_PAGES=1` → only the first page of each term is requested.

### US-007: Extensible sources

**As a** maintainer, **I want** to add a job board by adding its scraper and registering it, **so that** the product can grow without touching the API code. (FR-10)

Acceptance criteria:

- AC-1: Given a new source is registered, when the API starts, then `GET /jobs?source=<new-id>` is accepted and the OpenAPI document lists the new value, with no change in the API package.
- AC-2: Given a new source is registered, when a run executes, then it produces one result per term for the new source.

Edge cases:

- EC-1: `GET /jobs?source=linkedin` for an unregistered source → `422` with `validation_error` naming the `source` field.

## Relevance

### US-008: Relevance filter

**As an** API consumer, **I want** only software development jobs stored, **so that** the developer job bank is not polluted by unrelated openings such as "Programador de CNC". (FR-11, FR-12)

Acceptance criteria:

- AC-1: Given a collected title contains an include keyword and no exclude keyword (e.g. "Desenvolvedor Python Pleno"), when the run is ingested, then the job is stored.
- AC-2: Given a collected title contains no include keyword (e.g. "Analista de Suporte"), when the run is ingested, then the job is not stored and the combination's `discarded` count includes it.
- AC-3: Given a collected title contains an exclude keyword (e.g. "Programador de CNC"), when the run is ingested, then the job is not stored and is counted as discarded.
- AC-4: Given the keyword lists are changed through configuration, when the next run executes, then the new lists apply.
- AC-5: Matching ignores case and accents and works on whole words: "Desenvolvedor" matches `desenvolvedor`, "Produção" matches `producao`, and "DevOps" does **not** match `dev`.

Edge cases:

- EC-1: An already stored job's title changes to one that no longer passes the filter → it is discarded in this run, so `last_seen_at` is not updated and it eventually becomes inactive.
- EC-2: An empty `RELEVANCE_INCLUDE_KEYWORDS` → configuration error at startup (exit code `2` for the CLI; the service refuses to start).

### US-009: Seniority

**As an** API consumer, **I want** each job's seniority derived from its title, **so that** I can filter openings by level. (FR-13)

Acceptance criteria:

- AC-1: Given the title contains a seniority keyword, when the job is stored, then `seniority` is `intern`, `junior`, `mid` or `senior` according to the keyword table in `_spec.md` › Business Rules.
- AC-2: Given the title contains no seniority keyword, when the job is stored, then `seniority` is `null`.

Edge cases:

- EC-1: The title contains two levels ("Desenvolvedor Júnior/Pleno") → the left-most keyword wins (`junior`).
- EC-2: "PL/SQL" in a title does not count as `mid`.

## Lifecycle

### US-010: Active and inactive jobs

**As an** API consumer, **I want** to see only jobs seen recently by default, **so that** I don't waste time on openings that are probably closed, while history is kept. (FR-14, FR-15, FR-16, FR-19)

Acceptance criteria:

- AC-1: Given a job's `last_seen_at` is within the last 7 days, when I search without options, then it is returned with `"active": true`.
- AC-2: Given a job's `last_seen_at` is older than 7 days, when I search without options, then it is not returned.
- AC-3: Given the same job, when I search with `include_inactive=true`, then it is returned with `"active": false`.
- AC-4: Given an inactive job is collected again, when the run finishes, then it is active again.
- AC-5: Given `JOB_INACTIVE_AFTER_DAYS=3`, when the API restarts, then the threshold becomes 3 days.

Edge cases:

- EC-1: A job seen exactly 7 days ago to the second → still active (the threshold is "more than").
- EC-2: `GET /jobs/{id}` for an inactive job → returned with `"active": false` (the detail endpoint never hides by activity).

## Search API

### US-011: Text search

**As an** API consumer, **I want** to search jobs by text across title, company and description, **so that** I find openings matching my interests. (FR-17)

Acceptance criteria:

- AC-1: Given a job titled "Desenvolvedor Python", when I call `GET /jobs?q=python`, then it is returned.
- AC-2: Given a job whose company is "Bom Futuro", when I call `GET /jobs?q=bom futuro`, then it is returned.
- AC-3: Given a job whose description mentions "migração", when I call `GET /jobs?q=MIGRACAO`, then it is returned (case- and accent-insensitive).

Edge cases:

- EC-1: `q` is blank or only spaces → treated as absent; all jobs that match the other filters are returned.
- EC-2: `q` contains `%`, `_` or `'` → matched literally, never as a wildcard or syntax; no error.
- EC-3: `q` longer than 100 characters → `422 validation_error` naming `q`.
- EC-4: No job matches → `200` with an empty `items` list and `total` = 0.

### US-012: Filters

**As an** API consumer, **I want** to filter by source, location, seniority and the period in which jobs were seen, **so that** I narrow results down. (FR-18)

Acceptance criteria:

- AC-1: `GET /jobs?source=infojobs` returns only Infojobs jobs; `source=vagas&source=infojobs` returns both.
- AC-2: `GET /jobs?location=sao paulo` returns jobs whose location contains "São Paulo", ignoring case and accents.
- AC-3: `GET /jobs?seniority=senior&seniority=mid` returns only senior and mid jobs.
- AC-4: `GET /jobs?seen_from=2026-10-01&seen_to=2026-10-15` returns jobs seen at some point in that period, i.e. first seen on or before 2026-10-15 and last seen on or after 2026-10-01 (dates in `SCRAPE_TIMEZONE`).
- AC-5: Filters combine with AND across parameters and with OR within a repeated parameter.

Edge cases:

- EC-1: `seen_from` later than `seen_to` → `422` with code `invalid_period`.
- EC-2: `seniority=lead` (unknown value) → `422 validation_error` naming `seniority`.
- EC-3: A malformed date (`seen_from=31/10/2026`) → `422 validation_error` naming `seen_from`.
- EC-4: A period filter combined with the default active-only rule → both apply; an old period returns only jobs that are both in the period and still active, unless `include_inactive=true`.

### US-013: Pagination and ordering

**As an** API consumer, **I want** paginated results ordered from most recent, **so that** new openings come first and responses stay small. (FR-20)

Acceptance criteria:

- AC-1: Without parameters, the response has `page` = 1, `size` = 20, up to 20 `items`, `total` and `pages`.
- AC-2: Items are ordered by `last_seen_at` descending, then `first_seen_at` descending, then `id` descending.
- AC-3: `GET /jobs?page=2&size=50` returns items 51–100 of the ordered result.

Edge cases:

- EC-1: `size=101` or `size=0` → `422 validation_error` naming `size`.
- EC-2: `page=0` → `422 validation_error` naming `page`.
- EC-3: `page` beyond the last page → `200` with empty `items` and the real `total` and `pages`.
- EC-4: Jobs are ingested while I page through results → pages may shift; no error (no snapshot guarantee).

### US-014: Job detail

**As an** API consumer, **I want** to get one job by id, **so that** I can see its full data and follow its link to apply. (FR-21)

Acceptance criteria:

- AC-1: Given job 42 exists, when I call `GET /jobs/42`, then I receive it with all its fields, including `url` pointing to the original posting.

Edge cases:

- EC-1: `GET /jobs/999999` for an unknown id → `404` with code `job_not_found`.
- EC-2: `GET /jobs/abc` → `422 validation_error` naming `job_id`.

### US-015: Interactive documentation

**As a** technical evaluator, **I want** interactive API documentation, **so that** I can explore and call the endpoints without reading the code. (FR-22)

Acceptance criteria:

- AC-1: `GET /docs` serves Swagger UI listing every endpoint in `_dx.md`, with parameters, response schemas and error responses.
- AC-2: `GET /openapi.json` returns the OpenAPI document.

## Operations

### US-016: Health check

**As a** maintainer, **I want** a health endpoint, **so that** I and Docker Compose can tell whether the API and its database are working. (FR-23)

Acceptance criteria:

- AC-1: Given the database is reachable, `GET /health` returns `200` with `{"status": "ok", "database": "ok"}`.
- AC-2: Given the database is unreachable, `GET /health` returns `503` with `{"status": "unavailable", "database": "unreachable"}` within 3 seconds.

## Run history

### US-017: List collection runs

**As a** maintainer, **I want** to list collection runs, **so that** I can tell whether today's collection worked. (FR-24, FR-26)

Acceptance criteria:

- AC-1: `GET /collection-runs` returns runs ordered from most recently started, paginated like `/jobs`, each with `id`, `trigger`, `status`, `started_at`, `finished_at`, `error` and `totals` (`new`, `seen_again`, `discarded`).
- AC-2: A run in progress appears with status `running` and `finished_at` = `null`.

Edge cases:

- EC-1: No runs yet → `200` with empty `items`.
- EC-2: A run interrupted by a crash → shown as `running` until the next collection start marks it `failed` with error `interrupted` (US-003.EC-2).

### US-018: Run detail

**As a** maintainer, **I want** to see one run with its per-site, per-term results, **so that** I know exactly what failed and why. (FR-25, FR-26)

Acceptance criteria:

- AC-1: `GET /collection-runs/7` returns the run plus `results`: one entry per source × term with `source`, `term`, `status`, `pages`, `new`, `seen_again`, `discarded` and `error`.
- AC-2: `totals` equals the sum of `new`, `seen_again` and `discarded` across `results`.

Edge cases:

- EC-1: Unknown id → `404` with code `collection_run_not_found`.
- EC-2: A run still `running` → `results` is an empty list (results are recorded when the run completes).

## Developer experience

### US-019: One-command startup

**As a** technical evaluator, **I want** to start the database, migrations, API and scheduler with one command, **so that** I can see the system working without setup steps. (FR-27)

Acceptance criteria:

- AC-1: Given a clean clone and Docker running, when I run `docker compose up --build`, then these happen in order: the database becomes healthy, then migrations apply, then the API and the scheduler start. The API answers `GET /health` with `200` on `http://localhost:8000`, and the scheduler starts the initial collection.
- AC-2: Given the initial collection finished, when I call `GET /jobs`, then real jobs are returned, within 15 minutes of the command (objective O4).

Edge cases:

- EC-1: No `.env` file exists → the system starts with the documented defaults.
- EC-2: Port 8000 is already in use → Docker Compose fails with its port-in-use error; the README documents `API_PORT` to change it.
- EC-3: `docker compose up` is run again on an existing volume → migrations are a no-op, and data is kept. No startup collection runs if jobs exist **and** a run finished with a start in the last 24 hours; otherwise a startup collection runs (US-004.AC-4).

### US-020: Configuration through environment

**As a** maintainer, **I want** all settings to come from environment variables with a documented example file and no committed secrets, **so that** I can change behavior without editing code. (FR-03, FR-28)

Acceptance criteria:

- AC-1: Every key in `_dx.md` › Config is read from the environment and has the documented default.
- AC-2: `.env.example` lists every key with its default and a one-line comment; `.env` is git-ignored.
- AC-3: The repository contains no real credential; the only password is the local development default for a database port that is not published to the host.

Edge cases:

- EC-1: A numeric key with a non-numeric value (`SCRAPE_MAX_PAGES=abc`) → the service refuses to start with an error naming the key (exit code `2` for the CLI).
- EC-2: An invalid cron expression in `SCRAPE_CRON` → the scheduler refuses to start with an error naming the key.
- EC-3: An unknown time zone in `SCRAPE_TIMEZONE` → the scheduler refuses to start with an error naming the key.
- EC-4: `RELEVANCE_EXCLUDE_KEYWORDS=` (empty) in `.env` under Docker Compose → no exclusions apply; the default list is **not** substituted.
- EC-5: `SCRAPE_CRON=0 6 * * 0` → runs on Sundays (standard cron day-of-week), not Mondays.

### US-021: Continuous integration

**As a** technical evaluator, **I want** lint, architecture checks and tests to run on every push and pull request, **so that** I can trust the code quality shown. (FR-29, FR-30)

Acceptance criteria:

- AC-1: Every push and pull request runs format check, lint, import-boundary check and the full test suite, and the README shows the CI status badge.
- AC-2: The test suite passes with no network access to vagas.com or Infojobs.
- AC-3: CI fails when coverage of the domain and application layers is below 80%.

### US-022: Visible evolution

**As a** technical evaluator, **I want** to compare v1 with v2 and read the SDD artifacts, **so that** I understand how and why the project evolved. (FR-31, FR-32, FR-33)

Acceptance criteria:

- AC-1: The README explains what the project is, how to run it, how to query it, how to configure it, and has a "v1 → v2" section mapping each v1 problem to its v2 resolution.
- AC-2: `git show v1` resolves to commit `52018b3`.
- AC-3: `docs/tasks/fastapi-refactor/` contains the PRD, this spec and its companions, the task files, review rounds and workflow memory.
