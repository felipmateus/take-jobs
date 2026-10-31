"""UT-001-UT-013, UT-015, UT-018, UT-019: pure domain rules (Business Rules 4-15)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger

from take_jobs.config import (
    DEFAULT_RELEVANCE_EXCLUDE_KEYWORDS,
    DEFAULT_RELEVANCE_INCLUDE_KEYWORDS,
)
from take_jobs.domain.models import CombinationResult, ResultStatus, RunStatus, Seniority
from take_jobs.domain.rules import (
    RelevancePolicy,
    classify_seniority,
    final_run_status,
    normalize,
    startup_collection_reason,
    to_standard_crontab,
)


@pytest.fixture
def default_policy() -> RelevancePolicy:
    return RelevancePolicy(DEFAULT_RELEVANCE_INCLUDE_KEYWORDS, DEFAULT_RELEVANCE_EXCLUDE_KEYWORDS)


def test_ut001_normalize_lowercases_strips_accents_and_punctuation() -> None:
    assert (
        normalize("Desenvolvedor Sênior (Back-End) — São Paulo")
        == "desenvolvedor senior back end sao paulo"
    )


def test_ut002_normalize_blank_is_empty() -> None:
    assert normalize("  ") == ""


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Desenvolvedor Python Pleno", True),  # UT-003
        ("Analista de Suporte", False),  # UT-004
        ("Programador de CNC", False),  # UT-005
        ("PROGRAMADOR DE PRODUÇÃO", False),  # UT-006
        ("Analista DevOps", False),  # UT-007: `dev` matches whole words only
        ("Engenheiro(a) Front-end React", True),  # UT-008
    ],
)
def test_ut003_to_ut008_default_relevance(
    default_policy: RelevancePolicy, title: str, expected: bool
) -> None:
    assert default_policy.is_relevant(title) is expected


def test_ut009_empty_include_is_rejected() -> None:
    with pytest.raises(ValueError, match="include keywords must not be empty"):
        RelevancePolicy(include=[], exclude=["cnc"])


def test_relevance_include_made_only_of_blank_keywords_is_rejected() -> None:
    with pytest.raises(ValueError, match="include keywords must not be empty"):
        RelevancePolicy(include=[" ", "--"], exclude=[])


def test_relevance_empty_exclude_means_no_exclusions() -> None:
    policy = RelevancePolicy(include=["dev"], exclude=[])

    assert policy.is_relevant("Dev de Produção") is True


def test_relevance_keywords_are_normalized_and_match_phrases() -> None:
    policy = RelevancePolicy(include=["Full-Stack"], exclude=["Manutenção"])

    assert policy.is_relevant("Desenvolvedor FULL STACK") is True
    assert policy.is_relevant("Desenvolvedor Full Stack de Manutenção") is False
    assert policy.is_relevant("Fullstack") is False  # a different word, not the phrase


def test_relevance_matches_only_whole_words() -> None:
    policy = RelevancePolicy(include=["dev"], exclude=[])

    assert policy.is_relevant("Dev Python") is True
    assert policy.is_relevant("Device Engineer") is False
    assert policy.is_relevant("") is False


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Estagiário de Desenvolvimento", Seniority.INTERN),
        ("Desenvolvedor Jr", Seniority.JUNIOR),
        ("Trainee Dev", Seniority.JUNIOR),
        ("Dev Pleno", Seniority.MID),
        ("Desenvolvedor Sênior", Seniority.SENIOR),
        ("Tech Lead Java", Seniority.SENIOR),
        ("Especialista .NET", Seniority.SENIOR),
        ("Desenvolvedor Mid Level", Seniority.MID),
        ("Internship Backend", Seniority.INTERN),
    ],
)
def test_ut010_seniority_levels(title: str, expected: Seniority) -> None:
    assert classify_seniority(title) is expected


def test_ut011_no_keyword_means_none() -> None:
    assert classify_seniority("Desenvolvedor Python") is None


def test_ut012_leftmost_keyword_wins() -> None:
    assert classify_seniority("Desenvolvedor Júnior/Pleno") is Seniority.JUNIOR
    assert classify_seniority("Desenvolvedor Pleno/Júnior") is Seniority.MID


def test_ut013_pl_sql_is_not_mid() -> None:
    assert classify_seniority("Desenvolvedor PL/SQL") is None


def test_seniority_matches_whole_words_only() -> None:
    assert classify_seniority("Desenvolvedor Leader Pro") is None
    assert classify_seniority("Midway Developer") is None


def _result(status: ResultStatus) -> CombinationResult:
    return CombinationResult(
        source="vagas",
        term="dev",
        status=status,
        pages=1,
        new=0,
        seen_again=0,
        discarded=0,
        error=None if status is ResultStatus.SUCCESS else "boom",
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([ResultStatus.SUCCESS, ResultStatus.SUCCESS], RunStatus.SUCCESS),
        ([ResultStatus.SUCCESS, ResultStatus.FAILED], RunStatus.PARTIAL),
        ([ResultStatus.FAILED, ResultStatus.FAILED], RunStatus.FAILED),
        ([ResultStatus.FAILED, ResultStatus.SUCCESS, ResultStatus.FAILED], RunStatus.PARTIAL),
        ([], RunStatus.FAILED),
    ],
)
def test_ut015_final_run_status(statuses: list[ResultStatus], expected: RunStatus) -> None:
    assert final_run_status([_result(status) for status in statuses]) is expected


NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("store_empty", "latest", "expected"),
    [
        (True, None, "empty_job_store"),
        (True, datetime(2026, 10, 30, 9, 0, tzinfo=UTC), "empty_job_store"),
        (False, None, "no_recent_run"),
        (False, datetime(2026, 10, 29, 11, 59, tzinfo=UTC), "no_recent_run"),
        (False, datetime(2026, 10, 29, 12, 0, tzinfo=UTC), None),
        (False, datetime(2026, 10, 30, 9, 0, tzinfo=UTC), None),
    ],
)
def test_ut018_startup_collection_reason(
    store_empty: bool, latest: datetime | None, expected: str | None
) -> None:
    assert startup_collection_reason(store_empty, latest, NOW) == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 6 * * *", "0 6 * * *"),
        ("0 6 * * 0", "0 6 * * sun"),
        ("0 6 * * 7", "0 6 * * sun"),
        ("0 6 * * 1-5", "0 6 * * mon,tue,wed,thu,fri"),
        ("0 6 * * 0-4", "0 6 * * sun,mon,tue,wed,thu"),
        ("0 6 * * 0-6", "0 6 * * sun,mon,tue,wed,thu,fri,sat"),
        ("0 6 * * 5-7", "0 6 * * sun,fri,sat"),
        ("0 6 * * */2", "0 6 * * sun,tue,thu,sat"),
        ("0 6 * * sun-thu", "0 6 * * sun,mon,tue,wed,thu"),
        ("30 22 * * 6,0", "30 22 * * sun,sat"),
        ("0 6 * * FRI,Mon", "0 6 * * mon,fri"),
        ("0 6 * * 1-5/2", "0 6 * * mon,wed,fri"),
        ("0 6 * * 5/2", "0 6 * * sun,fri"),
        ("0 6 1 * 1", "0 6 1 * mon"),
    ],
)
def test_ut019_to_standard_crontab(expr: str, expected: str) -> None:
    result = to_standard_crontab(expr)

    assert result == expected
    CronTrigger.from_crontab(result)  # accepted by APScheduler


@pytest.mark.parametrize(
    "expr",
    [
        "0 6 * * 8",
        "0 6 * * 5-2",
        "0 6 * * */0",
        "0 6 * * */x",
        "0 6 * * mon-",
        "0 6 * * ,1",
        "0 6 * * foo",
        "0 6 * *",
        "0 6 * * * *",
    ],
)
def test_ut019_invalid_crontab_raises(expr: str) -> None:
    with pytest.raises(ValueError, match=r"cron|day-of-week"):
        to_standard_crontab(expr)


@pytest.mark.parametrize("expr", ["0 6 * * 0", "0 6 * * 0-4"])
def test_ut019_next_fire_time_from_friday_is_sunday(expr: str) -> None:
    zone = ZoneInfo("America/Sao_Paulo")
    trigger = CronTrigger.from_crontab(to_standard_crontab(expr), timezone=zone)
    friday = datetime(2026, 10, 30, 12, 0, tzinfo=zone)

    assert trigger.get_next_fire_time(None, friday) == datetime(2026, 11, 1, 6, 0, tzinfo=zone)
