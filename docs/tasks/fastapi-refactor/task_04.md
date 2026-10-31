---
status: completed
title: "Task 4: Scraping: parsers, spiders and the spawned crawl child"
type: backend
complexity: critical
---

# Task 4: Scraping: parsers, spiders and the spawned crawl child

## Overview

This task builds the collection engine and implements the `JobScraper` port with `ScrapyJobScraper`:
- fixture capture from the live sites, done once;
- pure parsers for vagas.com and Infojobs;
- one spider per source that walks every term;
- the source registry with `base_url`;
- the scraper itself, which runs the crawl in a `spawn` child process and hands the report back without deadlock.

The scraper also supports interruption and a test network guard that holds inside the child.

## Shippable Outcome

- **Outcome:** `ScrapyJobScraper(SOURCES, settings).scrape(terms)` returns a `ScrapeReport` with one outcome per source × term. It respects robots.txt and the 1 req/s per-site limit, paginates within bounds, and records per-term errors (`HTTP …`, `blocked by robots.txt`, `<ExceptionType>: <message>`, `parse error: …`). It never deadlocks on large reports and is stopped by `interrupt()` within 5 seconds.
- **Verify in this task:** UT-030–UT-049 and UT-106–UT-109 (parsers, spiders, child process), UT-116 (network guard in the child, using a real Scrapy request) and UT-119 (the `finished` close reason never reads as success).
- **Integration verification:** IT-007 and IT-013 in task_06 exercise the scraper together with the database.

## Requirements

- **Fixture capture (once).** Capture the fixtures listed in `_tests.md` › Strategy from the live sites with `SCRAPE_USER_AGENT` (OQ-1 resolved: honest UA):
  - `vagas_python_p1.html`, `vagas_python_p2_xhr.html` and `vagas_programador_p2_xhr.html` (renamed in review round 7);
  - `infojobs_python_p1.html` and `empty_listing.html`;
  - the synthetic `journey_*.html` pages for task_07's E2E tests.

  Trim the captures to what the tests need. Verify every default term's slug against the live sites (Known Risk R2) and record the results in task memory. **If a site blocks the honest UA, stop and return to the user**; do not switch UA silently. This is the only step with network access.
- **Field mapping and URLs:** field mapping per `_spec.md` › Integration Points. Every URL is resolved with `urljoin(page_url, …)`. `allowed_domains` comes from `base_url`, and an off-origin follow-up fails the term as `parse error: OffOriginURLError: …`.
- **Sanitization:** apply rule 27.
- **Per-term spider state:** seen ids, pages, a finished flag and an error. Stop conditions follow rule 17. Errbacks and the `spider_error` handler are both mandatory (rule 28, ADR-002).
- **Scrapy settings** per UT-048, including `TWISTED_REACTOR=None`, `DOWNLOAD_TIMEOUT=30` and `CLOSESPIDER_TIMEOUT=(timeout − 10) × 60`.
- **Child process** (`_spec.md` data flow step 3, Safety Invariants 5 and 7):
  - the child sets SIGINT to `SIG_IGN` and runs `process.start(install_signal_handlers=False)`;
  - the parent closes the child's end of the pipe, waits on `connection.wait`, and reads the report **before** `join`;
  - the close-reason mapping covers `finished`, `closespider_timeout` and anything else;
  - `interrupt()` before or after the child starts.
- **Test guard:** `install_test_socket_guard` lives in `tests/support/`. It patches both `connect` and `connect_ex`, and takes an optional `allow_hosts`.

## Subtasks

- [x] 4.1 Capture and trim the fixtures, and verify the slugs (network, once; record in memory).
- [x] 4.2 Write the vagas.com and Infojobs parsers (pure), with sanitization and URL resolution.
- [x] 4.3 Write the spiders with per-term state, stop rules, errbacks and the `spider_error` handler; add the registry and `with_base_url`.
- [x] 4.4 Add `build_scrapy_settings` and the `ScrapyJobScraper` child process, hand-off, close-reason mapping and `interrupt()`.
- [x] 4.5 Write `install_test_socket_guard` and the unit tests.

## Implementation Details

### Relevant Files

- `src/take_jobs/infrastructure/scraping/{registry,settings,scraper,slug}.py`, `parsers/{vagas,infojobs}.py`, `spiders/{vagas,infojobs}.py` — new.
- `tests/fixtures/html/*.html` — captured fixtures.
- `tests/support/socket_guard.py`, `tests/support/fixture_server.py` — test seams, also used by task_06 and task_07.
- `tests/unit/scraping/test_*.py` — new.

### Dependent Files

- `src/take_jobs/domain/{models,ports,errors}.py` (task_02).

### External References

- Live listing pages `https://www.vagas.com.br/vagas-de-python` and `https://www.infojobs.com.br/vagas-de-emprego-python.aspx?page=1` — field mapping source, observed on 2026-10-30 (`_spec.md` › External References).

### Related ADRs

- [ADR-002](adrs/adr-002.md) — three-phase collection, the spawn child, hand-off order, errbacks and signals.
- [ADR-003](adrs/adr-003.md) — one spider per source walking all terms.

## Deliverables

- Fixtures, parsers, spiders, registry, scraper and test guard.
- Passing unit tests.

## Tests

- [x] UT-030–UT-039 — parsers: field mapping, XHR pages, sanitization, URL resolution, off-origin guard.
- [x] UT-040–UT-049 — spiders: slugs, start requests, paging, stop rules, errors, settings, `spider_error`.
- [x] UT-106–UT-109 — child process: close reasons, interruption, crash without hang, large report without deadlock.
- [x] UT-116 — the network guard in the child blocks a real Scrapy request (0 server hits).
- [x] UT-119 — the `finished` close reason for an unfinished term is an error, never success; recorded outcomes are kept.

## Success Criteria

- No test reaches vagas.com or Infojobs. Only subtask 4.1 touches the network, and it is not part of the test suite.
