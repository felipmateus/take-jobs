---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_tests.md
line: 20
severity: medium
author: claude-code
provider_ref:
---

# Issue 008: No fixture/test for the vagas.com XHR follow-up page parsed on 2–20

## Review Comment

**Problem.** `_spec.md` › Integration Points (line 555) records that vagas.com follow-up pages come from `a#maisVagas@data-url` and need `X-Requested-With: XMLHttpRequest`, or the site answers 403. So pages 2–20 are AJAX responses, most likely an HTML fragment rather than the full document in `vagas_python_p1.html`. The fixture list (`_tests.md` lines 19–23) has only:
- `vagas_python_p1.html`, a full page;
- `vagas_python_last.html`, with no stated origin (full page or XHR fragment).

UT-042 asserts only that the follow-up request is *built*. No test parses the response the spider actually gets for pages 2–20, or checks that `next_url` is found in it. If the fragment's markup differs (no wrapping container, `#maisVagas` placed differently, relative `data-url`), every vagas term silently stops after page 1, and still reports `success`. That defeats the 20-page bound and most of the vagas volume.

**Suggested fix.**
- In task 3, capture `vagas_python_p2_xhr.html`: the raw XHR response for page 2, fetched with the same headers.
- State that `vagas_python_last.html` is the last XHR fragment.
- Add a UT: `parse_listing` on the p2 fragment returns > 0 jobs and a `next_url` for page 3.

## Triage

- Decision: `VALID`
- Notes: Root cause: no fixture for the XHR follow-up response parsed on pages 2-20.
- Fix applied (spec-only round, no code exists): _tests.md fixtures vagas_python_p2_xhr.html (last) and vagas_desenvolvedor_p2_xhr.html (middle); UT-032, UT-037, UT-042; IT-007 serves the p2 fragment; _spec.md Integration Points.
- Verified (round 2): fixtures `vagas_python_p2_xhr.html` (last) and `vagas_desenvolvedor_p2_xhr.html` (middle) defined; UT-032, UT-037, UT-042 parse the XHR responses; IT-007 serves the fragment for the follow-up URL and asserts `pages == 2`; Integration Points updated.
