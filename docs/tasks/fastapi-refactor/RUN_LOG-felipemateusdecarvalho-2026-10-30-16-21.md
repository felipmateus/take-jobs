# RUN_LOG — grill-me / grilling — take-jobs PRD

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 16:21
- **Skill:** `/grill-me` (redirects to `grilling`)
- **Goal:** answer the sections of `prd-template.md` to write the take-jobs v2 PRD
- **Output:** [`_prd.md`](_prd.md)

## Context: decisions made before the skill

These questions were asked in the same session before the skill started. They are included so the log is complete.

| Question | User's answer |
|---|---|
| Qual stack de backend você quer na versão refatorada? | "refatorar usando fast api, porém não vai ter a função para websocket mais pois eu tinha feito isso para mostrar a velocidade que as spiders pegavam os dados . deve ser fast api, com arquitetura em camadas usando injeção de dependencia." |
| Qual banco de dados usar? | "por que SQL Alchemy?" (follow-up question, answered below) |
| E o frontend (home e a tabela em tempo real)? | "não haverá conexão com web socket" |
| O que mais deve entrar na refatoração? | Docker Compose, Testes, Tooling moderno, README novo |
| Como a camada de persistência deve acessar o banco? | SQLAlchemy 2 + Alembic |
| Qual banco de dados? | PostgreSQL |
| Sem WebSocket, como as spiders devem ser disparadas? | "um chron job deve rodar as spiders uma vez ao dia" |
| A API ainda deve servir alguma página HTML? | Só API JSON |
| Escrevo a spec com cy-create-spec antes de implementar? | "você montou a spec antes de implementar?" → "primeiro vamos criar o prd com ajuda da skill /grill-me respondendo as perguntas do template do prd em anexo" |

## Round 1

| # | Question | Recommendation | User's answer |
|---|---|---|---|
| Q1 | Para quem é o produto? (a) portfólio, (b) ferramenta pessoal, (c) serviço para terceiros, (d) combinação | (d) portfólio primário + uso pessoal secundário | "a, quero mostrar minha evlução refatorando usando spec driven development" |
| Q2 | Problema que resolve: "Vagas ficam espalhadas em vários sites… o take-jobs coleta essas vagas todo dia e as expõe numa API única, padronizada e pesquisável." | Essa frase | "correto" |
| Q3 | Quem define os termos de busca? (a) lista fixa em configuração, (b) termos gerenciados pela API | (a) | "Vamos criar um banco de vagas de desenvolvedor. Então deve fazer um lista dos nomes de carga de desenvolvedores." |
| Q4 | Sites cobertos: só vagas.com e Infojobs ou outros? | Só os dois, com extensibilidade como requisito | "correto" |
| Q5 | Campos de cada vaga (título, empresa, local, resumo, data publicada, site, URL, primeira/última vez vista) | Esses campos, sem página de detalhe | "correto" |
| Q6 | Ciclo de vida: (a) guardar tudo, (b) marcar inativa após N dias, (c) apagar após N dias | (b), N = 7 configurável | "b" |
| Q7 | Capacidades de busca: texto em título/empresa/descrição, filtros por site/local/período, paginação, detalhe por id | Tudo isso, busca textual simples | "correto" |
| Q8 | Visibilidade das execuções do cron: (a) só logs, (b) execuções registradas e consultáveis pela API | (b) | No answer in this round |
| Q9 | Falha parcial: o que acontece quando um site/termo falha? | Os demais continuam, status "parcial", sem retentativa no dia | No answer in this round |
| Q10 | Postura de scraping: robots.txt, 1 req/s por site, máx. 20 páginas por termo, só dados públicos | Todas | No answer in this round |
| Q11 | Acesso e ambiente: (a) sem auth, local/self-hosted, (b) API key + nuvem | (a) | No answer in this round |
| Q12 | Dados antigos, idioma, local do PRD | Começar do zero; PRD/README pt-BR, código em inglês; `docs/tasks/fastapi-refactor/_prd.md` | No answer in this round |

## Round 2

| # | Question | Recommendation | User's answer |
|---|---|---|---|
| Q8–Q11 | Re-asked (see round 1) | Same as round 1 | No answer in this round |
| Q12 | Re-asked (see round 1) | Same as round 1 | "tudo deve ser em inglês" |
| Q13 | Lista de cargos de desenvolvedor: desenvolvedor, programador, engenheiro de software, desenvolvedor backend/frontend/full stack/mobile/python/java/javascript/.net/php | Essa lista | "sim" |
| Q14 | Filtro de relevância: (a) salvar tudo, (b) descartar títulos sem palavra-chave de dev | (b), descartadas contadas na execução | No answer in this round |
| Q15 | Classificação: (a) fora do escopo, (b) senioridade, (c) senioridade + stack | (b) | No answer in this round |
| Q16 | Evolução visível: (a) artefatos SDD versionados, (b) seção "v1 → v2" no README, (c) tag `v1` | As três, tag em `52018b3` | No answer in this round |

## Round 3

Still-open questions consolidated in one table: Q8, Q9, Q10, Q11, Q12b (search terms in Portuguese, start from zero, PRD path), Q14, Q15, Q16. Recommendations were the same as in the earlier rounds.

**User's answer:** "seguir as recomendações"

## Round 4 (final)

| # | Question | Recommendation | User's answer |
|---|---|---|---|
| Q17 | Objetivos e métricas: rastreabilidade 100%, ruff 0 erros + cobertura ≥ 80%, onboarding ≤ 15 min com um comando, ≥ 95% de sucesso da coleta em 7 dias, ≥ 90% de relevância, p95 < 300 ms com 50 mil vagas | As seis | "seguir todos os recomendados" |
| Q18 | Primeira execução: (a) comando sob demanda, (b) coleta automática com banco vazio, (c) as duas | (c) | "seguir todos os recomendados" |
| Q19 | CI com GitHub Actions (lint + testes em push e PR)? | Sim | "seguir todos os recomendados" |
| Q20 | Cron diário às 06:00 `America/Sao_Paulo`, configurável? | Sim | "seguir todos os recomendados" |
| Q21 | Fora de escopo: WebSocket/frontend, auth/nuvem/multiusuário, termos via API, stack/ranking, página de detalhe, outros sites, notificações, migração MySQL, retentativa no dia | Confirmar tudo | "seguir todos os recomendados" |

## Shared-understanding confirmation

**Question:** O resumo das decisões está correto para eu escrever o PRD?
**User's answer:** "Sim, o entendimento está correto. Escreva o PRD em docs/tasks/fastapi-refactor/_prd.md e gere o RUN_LOG."
