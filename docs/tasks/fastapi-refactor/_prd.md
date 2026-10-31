# Product Requirements Document — take-jobs v2

## Overview

Developer job openings in Brazil are scattered across several job boards, each with its own search, layout and data format. Keeping track of them means repeating the same searches on every site, every day.

**take-jobs v2** is a developer job bank. It collects developer job openings from vagas.com and Infojobs once a day, keeps only the ones that are actually software development roles, and exposes them through a single, standardized and searchable JSON API.

The product is first and foremost a **portfolio project**. Its v1 (a Flask app with real-time WebSocket streaming of scraped items) is being rebuilt from scratch using **spec-driven development (SDD)**: PRD → tech spec → tasks → implementation → review. The repository itself is meant to show that evolution: the v1 code, the SDD artifacts, and the v2 result side by side.

## Objectives

Success means an evaluator can clone the repository, start it with one command, query real developer jobs, and trace every requirement in this document to the tasks and tests that delivered it.

| # | Objective | Metric | Target |
|---|---|---|---|
| O1 | SDD traceability | Functional requirements in this PRD covered by at least one task and at least one automated test | 100% |
| O2 | Code quality | Lint errors (ruff) | 0 |
| O3 | Code quality | Test coverage of the domain and application layers | ≥ 80% |
| O4 | Onboarding | Time from a clean clone to the API returning real jobs, using a single command | ≤ 15 min |
| O5 | Collection reliability | Share of site × search-term combinations completed successfully over 7 consecutive days, as reported by the collection run history | ≥ 95% |
| O6 | Relevance | Share of stored jobs that are genuinely software development roles, by manual review of a random sample of 50 | ≥ 90% |
| O7 | Performance | p95 latency of the job search endpoint with up to 50,000 stored jobs, running locally | < 300 ms |

Visible evolution is also an objective in itself:

- The SDD artifacts (this PRD, the tech spec, tasks, review rounds and workflow memory) are versioned under `docs/tasks/`.
- The README has a "v1 → v2" section listing the problems of v1 and how v2 addresses each one.
- A `v1` git tag marks the last commit of the original version (`52018b3`) for comparison.
- Continuous integration runs lint and tests on every push and pull request, and its status is visible on the repository.

## User Stories

### Personas

- **Technical evaluator (primary)** — a recruiter, interviewer or engineer assessing the author's work. Has limited time; wants to run the project quickly, read clean code and see evidence of process and quality.
- **Author as API consumer (secondary)** — the author, querying the job bank to follow developer openings.
- **Author as maintainer (secondary)** — the author, tuning search terms or adding a new job board later.

### Main flows

- As a **technical evaluator**, I want to start the whole system with a single command so that I can see it working without manual setup.
- As a **technical evaluator**, I want the API to already contain real jobs right after the first start so that I don't have to wait for the next daily run.
- As a **technical evaluator**, I want interactive API documentation so that I can explore the endpoints without reading the source code.
- As a **technical evaluator**, I want to compare v1 and v2 and read the SDD artifacts so that I can understand how the project evolved and why.
- As a **technical evaluator**, I want to see a passing CI status so that I can trust lint and tests run on every change.
- As an **API consumer**, I want to search jobs by text across title, company and description so that I can find openings that match my interests.
- As an **API consumer**, I want to filter jobs by source site, location, seniority and the period in which they were seen so that I can narrow results down.
- As an **API consumer**, I want results paginated and ordered from most recent so that I see new openings first.
- As an **API consumer**, I want to see only active jobs by default so that I don't waste time on openings that are probably closed.
- As an **API consumer**, I want to open a single job by its id and follow its link to the original posting so that I can apply.
- As a **maintainer**, I want to change the list of search terms, the schedule and the scraping limits through configuration so that I don't need to change code.
- As a **maintainer**, I want to check the history of collection runs so that I can tell whether today's collection worked and what failed.
- As a **maintainer**, I want to add a new job board without changing the API so that the product can grow.

### Edge cases

- A job board is down or its HTML changed: the other site × term combinations still complete, and the run is recorded as partial with the error.
- The same job appears for several search terms or on consecutive days: it is stored once, and its "last seen" date is updated.
- A search returns non-development jobs (e.g. "programador de CNC"): they are discarded and counted in the run history.
- A job board returns the first page again when asked for a page past the end: collection for that term stops instead of looping.
- A job stops appearing in the listings: after 7 days without being seen it becomes inactive, but stays in the history.
- The database is empty on first start: a collection runs immediately instead of waiting for the next scheduled time.
- A search or filter matches nothing: the API returns an empty page, not an error.
- A job id that does not exist is requested: the API returns a not-found error.

## Core Features

### F1 — Daily job collection

**What it does:** collects developer job openings from vagas.com and Infojobs for a configurable list of search terms, once a day.
**Why it matters:** it is the source of all data in the job bank and replaces v1's on-demand, unsafe scraping trigger.
**How it works:** a scheduler starts a collection run at a configured time. For each source site and each search term, the run reads the public listing pages, extracts the job fields and stores them.

- **FR-01** The system must collect jobs from vagas.com and Infojobs.
- **FR-02** The system must run a collection once a day, by default at 06:00 in the `America/Sao_Paulo` time zone; both time and time zone must be configurable.
- **FR-03** The search terms must be configurable. The default list is: `desenvolvedor`, `programador`, `engenheiro de software`, `desenvolvedor backend`, `desenvolvedor frontend`, `desenvolvedor full stack`, `desenvolvedor mobile`, `desenvolvedor python`, `desenvolvedor java`, `desenvolvedor javascript`, `desenvolvedor .net`, `desenvolvedor php`.
- **FR-04** For each job, the system must store: title, company, location, summary/description as shown in the listing, publication date as displayed by the site, source site, URL of the original posting, first-seen timestamp and last-seen timestamp.
- **FR-05** The same job collected more than once (across terms or days) must be stored only once; collecting it again updates its last-seen timestamp.
- **FR-06** At startup, the system must trigger a collection immediately when the database has no jobs, or when no collection has finished in the last 24 hours. *(Amended on 2026-10-30 by the user's decision during review round 1, issue 004: the second condition covers a machine that was off at the scheduled time.)*
- **FR-07** The system must provide a documented command to run a collection on demand.
- **FR-08** Collection must stop for a site × term combination when a page brings no job that was not already seen in that run, or when the page limit is reached.
- **FR-09** A failure in one site × term combination must not stop the others; failed combinations are not retried on the same day.
- **FR-10** It must be possible to add a new source site without changing the API.

### F2 — Relevance filtering and seniority

**What it does:** keeps only software development jobs and derives their seniority level.
**Why it matters:** job boards return unrelated openings for terms like "programador"; without filtering, the developer job bank loses its value. Seniority is one of the most useful filters for developers.
**How it works:** each collected job title is checked against configurable include and exclude keyword lists, and its seniority is inferred from the title.

- **FR-11** A job must be discarded when its title matches no include keyword or matches an exclude keyword (e.g. "cnc"). Both keyword lists must be configurable.
- **FR-12** Discarded jobs must not be stored, but their count must be recorded in the collection run history.
- **FR-13** The system must derive a seniority level from the job title: `intern`, `junior`, `mid` or `senior`, or leave it empty when it cannot be determined.

### F3 — Job lifecycle

**What it does:** distinguishes jobs that are probably still open from those that disappeared.
**Why it matters:** job postings expire; showing stale openings by default hurts the consumer, while deleting them would lose history.
**How it works:** a job not seen for a configurable number of days is considered inactive.

- **FR-14** A job not seen for more than 7 days (configurable) must be considered inactive.
- **FR-15** Inactive jobs must be kept in the database.
- **FR-16** A job that is seen again becomes active again.

### F4 — Job search API

**What it does:** exposes the job bank through a read-only JSON API.
**Why it matters:** it is the single, standardized access point that solves the scattered-listings problem.
**How it works:** consumers query a search endpoint with text, filters and pagination, and fetch individual jobs by id.

- **FR-17** The API must allow text search across title, company and description, case-insensitive and accent-insensitive.
- **FR-18** The API must allow filtering by source site, location, seniority and a seen-in-period range (from/to).
- **FR-19** The API must return only active jobs by default, with an option to include inactive ones.
- **FR-20** Results must be paginated, with the page size bounded by a maximum, and ordered from most recently seen; each page must report the total number of matching jobs.
- **FR-21** The API must return a single job by its id, and a not-found error for unknown ids.
- **FR-22** The API must expose interactive documentation (OpenAPI/Swagger).
- **FR-23** The API must expose a health check endpoint that reports whether the service and its database are reachable.

### F5 — Collection run history

**What it does:** records each collection run and makes it queryable.
**Why it matters:** it shows whether the daily collection is working and provides the data for objective O5.
**How it works:** every run is recorded with per-combination results and exposed by the API.

- **FR-24** Each collection run must record start time, end time and overall status: `success`, `partial` or `failed`.
- **FR-25** For each site × term combination, a run must record status, number of new jobs, number of jobs seen again, number of discarded jobs and the error message when it fails.
- **FR-26** The API must list collection runs, most recent first and paginated, and return a single run with its per-combination details.

### F6 — Developer experience and SDD evidence

**What it does:** makes the project easy to run and its evolution easy to inspect.
**Why it matters:** the primary persona is an evaluator with limited time; the portfolio value depends on it.
**How it works:** containerized setup, CI, documentation and versioned process artifacts.

- **FR-27** The whole system (API, database and scheduler) must start with a single command.
- **FR-28** All configuration (database credentials, schedule, search terms, limits, keywords) must come from environment variables, with a documented example file; no secret may be committed to the repository.
- **FR-29** CI must run lint and the full test suite on every push and pull request.
- **FR-30** Automated tests must not depend on the real job boards being reachable.
- **FR-31** The README must explain what the project is, how to run it, how to query the API, how to configure it, and include a "v1 → v2" section.
- **FR-32** A `v1` git tag must point to commit `52018b3`.
- **FR-33** All SDD artifacts for this refactor must be versioned under `docs/tasks/fastapi-refactor/`.

## User Experience

- **Technical evaluator journey:** opens the README → reads the overview and the "v1 → v2" section → runs one command → waits for the initial collection → opens the interactive API docs → searches jobs → optionally browses `docs/tasks/` and the CI history. The README must make this path obvious in its first screen.
- **API consumer journey:** calls the search endpoint with text and filters → pages through results → opens a job → follows the link to the original posting.
- **Maintainer journey:** edits the environment configuration → restarts → checks the collection run history to confirm the new settings took effect.
- **Interface:** there is no graphical interface. The API returns JSON only; the interactive OpenAPI documentation is the exploration interface.
- **API consistency:** field names, error format and pagination shape must be consistent across endpoints; errors must be descriptive and use appropriate HTTP status codes.
- **Language:** everything (code, API, documentation, PRD, README) is in English. Only the search terms are in Portuguese, because the source sites are Brazilian.
- **Accessibility:** not applicable to a JSON API; the README must use descriptive headings and alt text for any images.

## High-Level Technical Constraints

- **Non-negotiable technology:**
  - API built with FastAPI, in a layered architecture using dependency injection.
  - PostgreSQL as the database, accessed through SQLAlchemy 2, with schema changes versioned by Alembic migrations.
  - Docker Compose to run the system.
  - uv for dependency management, ruff for lint and formatting, pytest for tests.
  - GitHub Actions for CI.
- **External integrations:** public listing pages of vagas.com and Infojobs. Their HTML can change without notice, so source-specific parsing must be isolated and covered by tests using stored HTML samples.
- **Scraping conduct:**
  - Respect each site's robots.txt.
  - At most 1 request per second per site.
  - At most 20 listing pages per search term per run.
  - Both limits must be configurable.
  - Collect only public listing data, with no login.
- **Expected volume:** about 12 terms × 2 sites × up to 20 pages, which is at most about 480 requests per daily run, completing within roughly 10 minutes.
- **Performance:** job search p95 < 300 ms with up to 50,000 stored jobs, locally (O7).
- **Security:**
  - No credentials or secrets in the repository; v1 committed a database password, which must not happen again.
  - No user input may be passed to a shell.
- **Access:** no authentication; the API is read-only and intended to run locally or self-hosted.
- **Data and privacy:** only public job posting data is stored; no personal data about candidates or users is collected.
- **Data migration:** none. v2 starts with an empty database; v1 data is not migrated.

## Out of Scope

- Real-time streaming of collected jobs (WebSocket) and any HTML frontend.
- Authentication, multi-user support and cloud deployment.
- Managing search terms through the API.
- Classifying jobs by technology stack, and relevance ranking of search results.
- Opening each job's detail page to collect extra data (salary, full requirements).
- Job boards other than vagas.com and Infojobs (the product must allow adding them later, per FR-10).
- Notifications or alerts about new jobs.
- Migration of v1 MySQL data.
- Retrying failed collections on the same day.
