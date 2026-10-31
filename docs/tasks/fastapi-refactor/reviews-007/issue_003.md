---
provider: manual
pr:
round: 7
round_created_at: 2026-10-31T00:56:07Z
status: resolved
file: src/take_jobs/infrastructure/scraping/spiders/vagas.py
line: 19
severity: medium
author: claude-code
provider_ref:
---

# Issue 003: vagas.com `desenvolvedor` single page is unverified and implausible

## Review Comment

`memory/task_04.md` says live `vagas-de-desenvolvedor` returned a single page of 10 cards, and MAN-001 confirms that only `programador` paginated. The implementer accepted this as site behavior and replaced the contracted fixture. That deviation is not sound as recorded, for three reasons.

**The captured pages show the search is full-text and stemmed** (titles taken from the committed fixtures):
- `vagas_python_p1.html` (`/vagas-de-python`, no `q`): "Analista de Business Intelligence", "Analista Atuarial", "Estágio em Economia"…, so `python` matches descriptions, not titles.
- `vagas_desenvolvedor_p2_xhr.html` (actually `programador` page 2): "Programa Jovem Aprendiz", "Programa de Estágio…", "Assistente de Programação de Escala…", so `programador` matches related word forms. This is why the live run discarded 880 jobs.

Under that matching, `desenvolvedor` (whose forms include "desenvolvimento", common in job descriptions) returning **10 results, fewer than `python`'s 43**, is implausible. It points at the URL rather than the site's inventory. One candidate: `/vagas-de-{slug}` without `q` may resolve differently for some slugs than the site's own search, whose pager uses `?pagina=N&q=<term>`. A redirect to a narrower page is another possibility. The page-1 request is `{base_url}/vagas-de-{slug}` (`spiders/vagas.py:19-20`), with no `q`.

**The contracts expected otherwise, and the evidence was not kept:**
- `_dx.md`'s sample `collect` output shows `vagas desenvolvedor ok pages=20`.
- Task 3 / R2 required verifying each term "against the live sites". The check recorded is only "200 with a listing page", which cannot detect a wrong-but-valid URL.
- `_tests.md` names `vagas_desenvolvedor_p2_xhr.html` as desenvolvedor's XHR page 2. The file now holds `programador` page 2 under that name, and no `desenvolvedor` page 1 was captured. The repository therefore holds nothing that supports "10 cards, no next link".

**Impact if this is a URL bug:** vagas.com, the Motivating Problem's Slice 1 source, contributes only a handful of developer jobs (MAN-003 sampled 4 vagas jobs out of 50). The main term silently under-collects while its result row reads `success`.

**Live checks needed** (the reviewer did not access the site):
1. Fetch `https://www.vagas.com.br/vagas-de-desenvolvedor` with the honest UA. Save it untrimmed, and record the final URL (any 30x), the result count shown on the page, and whether `a#maisVagas` is present.
2. In a browser, search "desenvolvedor" with the site's own search box. Record the URL it produces and the result count.
3. Fetch `/vagas-de-desenvolvedor?q=desenvolvedor`, and the XHR `?pagina=2&q=desenvolvedor` with page 1's cookies and `X-Requested-With`. Compare the counts and ids with step 1.

**Resolution:**
- If the site really lists 10 jobs, record the count, the URL and the date in `memory/task_04.md`, and rename or annotate the substitute fixture so its name no longer claims to be `desenvolvedor`. That can close this issue.
- Otherwise, change `first_page_url` to the URL the site's search uses, capture real `desenvolvedor` page 1 and page 2 fixtures, and add a spider test for the corrected URL.

## Triage

- Decision: `VALID`
- Notes:
  - Live checks (2026-10-30, honest UA): `GET /vagas-de-desenvolvedor` answers 200 with no redirect, canonical URL equals the request URL, `<h1>10 vagas de emprego para desenvolvedor</h1>`, 10 cards (Desenvolvedor Java, Fullstack .net, Analista de Sistemas...), no `a#maisVagas`. The same day `programador` says "1136 vagas" (40 cards + `#maisVagas`) and `python` "43 vagas". XHR `?pagina=2&q=desenvolvedor` (cookies, `X-Requested-With`, `Referer`) answers 200 with no cards; non-XHR `?q=desenvolvedor` answers 403, like every non-XHR follow-up. The site's own search form posts to `/vagas/pesquisas`, which robots.txt disallows, so it was not fetched and step 2 of the issue (compare with the site's own search) could not be done; this is a limit of the evidence, recorded in `memory/task_04.md`.
  - Conclusion: the URL is the site's canonical landing page for the term and its own count is 10, so the `first_page_url` is correct and the "10 jobs, no next page, `success`" row is honest; the review's "URL bug" hypothesis is not supported. The finding is valid on the part that the repository held no evidence and the substitute fixture was misnamed.
  - Fix (the issue's first resolution branch): no spider change. Added the real trimmed `vagas_desenvolvedor_p1.html` fixture with a parser test (10 jobs, no next URL, `<h1>` says 10); renamed `vagas_desenvolvedor_p2_xhr.html` to `vagas_programador_p2_xhr.html` (it is `programador` page 2) in `test_parsers.py`, `_tests.md`, `task_04.md`; recorded count, URL and date in `memory/task_04.md`. `_dx.md`'s sample `vagas desenvolvedor ok pages=20` is illustrative output and stays.
  - Product note: vagas.com contributes few `desenvolvedor` jobs because the site lists few; that is site inventory, not under-collection.
- Verified (round 8): `tests/fixtures/html/vagas_desenvolvedor_p1.html` holds `<h1>10 vagas de emprego para desenvolvedor`, and `test_vagas_desenvolvedor_lists_a_single_page_of_ten` pins 10 jobs and no next URL. The misnamed fixture is now `vagas_programador_p2_xhr.html`; the old name appears in no test, source or contract file except the rename note in `_tests.md`. The live count, URL and date are recorded in `memory/task_04.md`, including the limit that the site's own search (`/vagas/pesquisas`) is robots-disallowed. That is the issue's first resolution branch.
