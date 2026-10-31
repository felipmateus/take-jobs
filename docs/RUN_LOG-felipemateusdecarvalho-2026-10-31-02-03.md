# Run log: `readme` skill (2026-10-31 02:03)

Skill: `readme`, on branch `fix/relevance-filter-readme-demo`.

## User request

> use uma skill para melhorar o readme do projeto. Acho que seria interessante colocar prints de resultados.

## Questions asked and answers

No questions were asked. The skill asks only when the purpose, deployment target or business context cannot be read from the code, and all three were clear from the repository.

## What was done

- Started the stack on an empty volume with `docker compose up --build -d`. The startup collection finished `success` in 1m07s (162 new, 298 seen again, 1,361 discarded; 24 of 24 combinations).
- Captured four new screenshots in `docs/images/`:
  - `collection-run-terminal.png`: the real scheduler output of that run.
  - `search-terminal.png`: a filtered search (`seniority=senior`) through `curl` and `jq`.
  - `swagger-search-jobs.png`: `GET /jobs?q=python&size=1` from Swagger "Try it out".
  - `swagger-collection-runs.png`: `GET /collection-runs` from Swagger "Try it out".
- README: added Contents, Key features, a screenshot-based Demo, a stack line in Overview and a Troubleshooting section. The other sections were kept.
- `uv run pytest tests/static`: 50 passed.
