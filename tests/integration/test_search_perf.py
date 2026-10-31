"""IT-011 (perf, O7): search latency at 50,000 jobs through the real `JobQueryService`.

The seed is generated from a fixed random seed and loaded with `COPY`. Two sets are measured:
searches with a 3+ character `q` (and the other filters), and searches with 1- and 2-character
`q` values, which a trigram index cannot serve (ADR-005 Risks). Each set must have a p95 below
300 ms. The measured numbers are printed (run with `-s`) and are what the task memory records.
"""

import math
import random
import statistics
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import and_, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from take_jobs.application.services import JobQuery, JobQueryService
from take_jobs.domain.models import JobSearchCriteria, Seniority
from take_jobs.infrastructure.db.job_repository import SqlAlchemyJobRepository, _conditions
from take_jobs.infrastructure.db.models import JobRow
from tests.fakes import FixedClock

pytestmark = pytest.mark.perf

JOBS = 50_000
P95_LIMIT_SECONDS = 0.300
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

ROLES = [
    "Desenvolvedor Python",
    "Desenvolvedor Java",
    "Desenvolvedor Backend",
    "Desenvolvedor Frontend React",
    "Desenvolvedor Full Stack",
    "Programador PHP",
    "Engenheiro de Software",
    "Desenvolvedor Mobile Flutter",
    "Desenvolvedor .NET",
    "Analista Desenvolvedor Node",
]
LEVELS = ["Estagio", "Junior", "Pleno", "Senior", "Sênior", ""]
COMPANIES = [
    "Acme Tecnologia",
    "Banco Horizonte",
    "Logística Ágil",
    "Fábrica de Software Alfa",
    "Rede Saúde Mais",
    "Educação Digital",
    "Mercado Livre Brasil",
    "Seguros União",
]
CITIES = [
    "São Paulo - SP",
    "Rio de Janeiro - RJ",
    "Porto Alegre - RS",
    "Belo Horizonte - MG",
    "Curitiba - PR",
    "Florianópolis - SC",
    "Recife - PE",
    "Brasília - DF",
]
WORDS = """
equipe projeto cliente sistema desenvolvimento integração serviço análise requisitos banco dados
nuvem testes entrega qualidade processo ambiente produção manutenção suporte arquitetura
documentação melhoria contínua metodologia ágil comunicação responsabilidade experiência
conhecimento tecnologia aplicação interface usuário relatório monitoramento
""".split()  # noqa: SIM905
RARE = ["kubernetes", "terraform", "kafka", "graphql", "elasticsearch"]
SOURCES = ["vagas", "infojobs"]


def _description(rng: random.Random) -> str:
    words: list[str] = []
    while sum(len(word) + 1 for word in words) < 300:
        words.append(rng.choice(WORDS))
    if rng.random() < 0.03:
        words[rng.randrange(len(words))] = rng.choice(RARE)
    return " ".join(words)[:300]


def _records() -> list[tuple]:
    rng = random.Random(20261030)
    records = []
    for number in range(JOBS):
        role, level = rng.choice(ROLES), rng.choice(LEVELS)
        title = f"{role} {level}".strip()
        seniority = {"Estagio": "intern", "Junior": "junior", "Pleno": "mid"}.get(level)
        if level in ("Senior", "Sênior"):
            seniority = "senior"
        seen = NOW - timedelta(days=rng.choice([0, 1, 2, 3, 5, 6, 20, 40]), hours=rng.randrange(24))
        records.append(
            (
                rng.choice(SOURCES),
                str(number),
                title,
                rng.choice(COMPANIES),
                rng.choice(CITIES),
                _description(rng),
                "28 out",
                f"https://example.test/vaga/{number}",
                seniority,
                seen - timedelta(days=rng.choice([0, 0, 1, 2])),
                seen,
            )
        )
    return records


COLUMNS = [
    "source",
    "external_id",
    "title",
    "company",
    "location",
    "description",
    "published_label",
    "url",
    "seniority",
    "first_seen_at",
    "last_seen_at",
]


@pytest.fixture
async def seeded(engine: AsyncEngine) -> None:
    records = _records()
    async with engine.connect() as connection:
        raw = await connection.get_raw_connection()
        await raw.driver_connection.copy_records_to_table("jobs", records=records, columns=COLUMNS)
        await connection.commit()
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text("ANALYZE jobs"))


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def measure(
    sessionmaker: async_sessionmaker[AsyncSession], queries: list[JobQuery]
) -> list[float]:
    timings: list[float] = []
    for query in queries:
        started = time.perf_counter()
        async with sessionmaker() as session:  # one session per request, as the API does
            service = JobQueryService(
                SqlAlchemyJobRepository(session),
                FixedClock(NOW),
                timedelta(days=7),
                ZoneInfo("America/Sao_Paulo"),
            )
            await service.search(query)
        timings.append(time.perf_counter() - started)
    return timings


def long_queries() -> list[JobQuery]:
    rng = random.Random(1)
    texts = ["python", "backend", "java", "desenvolvedor sênior", "kubernetes", "terraform"]
    queries = []
    for _ in range(50):
        queries.append(
            JobQuery(
                q=rng.choice(texts),
                location=rng.choice([None, "sao paulo", "Porto Alegre", "curitiba"]),
                sources=frozenset(rng.choice([[], ["vagas"], ["infojobs"], SOURCES])),
                seniorities=frozenset(
                    rng.choice([[], [Seniority.SENIOR], [Seniority.JUNIOR, Seniority.MID]])
                ),
                page=rng.choice([1, 1, 2, 5]),
                size=20,
            )
        )
    return queries


def short_queries() -> list[JobQuery]:
    values = ["go", "js", "ui", "c"]
    return [JobQuery(q=values[number % len(values)], size=20) for number in range(20)]


@pytest.mark.usefixtures("seeded")
async def test_it011_search_latency_at_50k_jobs(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    await measure(sessionmaker, long_queries()[:5])  # warm the connection pool and caches
    long_timings = await measure(sessionmaker, long_queries())
    short_timings = await measure(sessionmaker, short_queries())

    for label, timings in (("3+ characters", long_timings), ("1-2 characters", short_timings)):
        print(
            f"\nIT-011 {label}: n={len(timings)} "
            f"p50={statistics.median(timings) * 1000:.1f} ms "
            f"p95={p95(timings) * 1000:.1f} ms max={max(timings) * 1000:.1f} ms"
        )

    assert p95(long_timings) < P95_LIMIT_SECONDS
    assert p95(short_timings) < P95_LIMIT_SECONDS

    # A selective 3+ character `q` is served by the trigram index.
    statement = select(JobRow.id).where(
        and_(
            *_conditions(JobSearchCriteria(text="kubernetes", active_since=NOW - timedelta(days=7)))
        )
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    plan = "\n".join((await session.execute(text(f"EXPLAIN {sql}"))).scalars())
    assert "ix_jobs_search_text_trgm" in plan, plan
