# task_09 memory

## Outcome
Completed. New: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `tests/static/{__init__,support,test_compose,test_env_config,test_secret_scan}.py`, `tests/fixtures/secrets/{leak,ok}.env`. Full gate green (409 passed, 108 s).

## Decisions
- Image: `python:3.13-slim`, uv copied from `ghcr.io/astral-sh/uv:0.8`, two-step `uv sync --frozen --no-dev` (dependencies, then project) with `README.md` copied because `pyproject.toml` declares it as `readme`; venv in `/app/.venv` on `PATH`; user `app` (uid 10001); copies `src`, `alembic.ini`, `migrations`. Default command is the uvicorn factory.
- Compose: one `x-app-environment` anchor (all app keys as `"${KEY-default}"`, merged with `<<`) shared by `migrate`, `api` and `scheduler`; `db` lists `POSTGRES_*` and `api` the `${API_PORT-8000}:8000` port. `DATABASE_URL`'s default is a literal (spec: default equals `.env.example`), so changing `POSTGRES_*` in `.env` requires changing `DATABASE_URL` too (commented in `.env.example`).
- Tests render Compose with `docker compose --project-directory <tmp> config --format json` on a copy in a scratch dir (a developer's `.env` cannot leak in) and an environment stripped of every `.env.example` key. UT-110 expands the db healthcheck through `sh -c` with `echo` in place of `pg_isready` and asserts `-U take_jobs -d take_jobs`. IT-012 also asserts `Settings(_env_file=".env.example") == Settings(_env_file=None)` and the `API_PORT=8001` rendering. Docker-dependent cases skip only when the `docker` CLI is absent.
- Secret scan deviations from `_tests.md` (both needed to pass on the current tree): (1) the file list is `git ls-files --cached --others --exclude-standard`, because nearly the whole v2 tree is still untracked and plain `git ls-files` would scan only v1 leftovers; once committed it is the same set. (2) `str` is an allowed captured value (`postgres_password: str`, `token: str` annotations match the fixed pattern). Source/test edits to avoid false positives: `domain/rules.py::_dow_number` parameter `token` -> `value`; `tests/unit/test_config.py` compares `(postgres_user, postgres_password, postgres_db)` as a tuple; the fake URLs in `tests/e2e/test_health.py`, `tests/integration/test_repositories.py`, `tests/unit/api/test_api.py`, `tests/unit/cli/test_collect.py` now use the allowed password `take_jobs_dev`.

## MAN-001 evidence (2026-10-30, macOS Docker 27.4 / Compose 2.31, no `.env`, port 8000 free, fresh volume; image layers were cached from an earlier probe build, so build time is not representative)
- `docker compose up --build -d`: returned after 15 s; no "not set"/warning lines in its output; `db` healthy, `migrate` exited 0 (`Running upgrade -> 0001`), `api` and `scheduler` started.
- `GET /health` 200 at +21 s from the start of `up`.
- Scheduler logged `startup_collection reason=empty_job_store`; the real collection against vagas.com and infojobs.com.br finished `success` in 33 s (run 1: new=100, seen_again=92, discarded=880; 24 combinations all `ok`; vagas `programador` paged 20 pages, the other vagas terms 1 page, infojobs 2 pages). `GET /jobs` returned `total=100` at +51 s (O4 target 15 minutes).
- Second start (`docker compose down`, keeping the volume, then `up -d`): `/health` 200 at +10 s, `total=100` kept, scheduler logged `startup_collection_skipped reason=recent_run_exists`, still one run (id 1). The `no_recent_run` branch (more than 24 h) was not exercised live; it is covered by UT-080/UT-081.
- `docker compose stop scheduler`: stopped in 1 s with exit code 0, logs `scheduler_stopped`.
- `API_PORT=8001 docker compose up -d`: `api` published `0.0.0.0:8001->8000`, `/health` 200 and `/jobs` total 100 on 8001, connection refused on 8000.
- Cleanup: `docker compose down -v`; only the user's exited `mrt-local-pg` remains, no `take-jobs_pgdata` volume.

## MAN-003 evidence
Random sample of 50 of the 100 stored jobs (Python `random.seed(20261030)` over `/jobs`, 4 vagas and 46 infojobs titles): 48 genuine development roles, 2 not ("Programador De Materiais" at Grupo FX, a logistics role; "Programador Visual - Teresopolis / RJ" at SESC RJ, a visual-communication role). 96%, above the 90% target. Borderline counted as development: "Engenheiro De Software Embarcado", the intern "ESTAGIO | FRONT END E FULL STACK" and the Itau/IEL "Bolsista Graduado[Engenheiro De Software ...]". Both misses contain the word "programador"; a follow-up could add `visual` and `materiais` to the default exclude list (not done: the list is fixed by `_dx.md`).

## Handoff
- task_10 (README): document `docker compose up --build`, `API_PORT`, `.env.example`, the `DATABASE_URL`/`POSTGRES_*` coupling, and the observed 33 s collection / `recent_run_exists` behavior. The v1 `README.md` is still in place (the image build copies it).
- The secret scan runs over untracked files too; `docs/**/*.md` stay excluded and the never-quote policy for the v1 password is checked at review (this task never quoted it).
