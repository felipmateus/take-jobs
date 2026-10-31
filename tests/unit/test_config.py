from pathlib import Path

import pytest
from pydantic import ValidationError

from take_jobs.config import Settings

_KEYS = [
    "API_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DATABASE_URL",
    "SCRAPE_CRON",
    "SCRAPE_TIMEZONE",
    "SCRAPE_ON_START",
    "SCRAPE_RUN_TIMEOUT_MINUTES",
    "SCRAPE_TERMS",
    "SCRAPE_MAX_PAGES",
    "SCRAPE_DOWNLOAD_DELAY",
    "SCRAPE_USER_AGENT",
    "RELEVANCE_INCLUDE_KEYWORDS",
    "RELEVANCE_EXCLUDE_KEYWORDS",
    "JOB_INACTIVE_AFTER_DAYS",
    "LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def make_settings() -> Settings:
    return Settings(_env_file=None)


def test_ut020_defaults_with_empty_environment() -> None:
    settings = make_settings()

    assert settings.scrape_terms == [
        "desenvolvedor",
        "programador",
        "engenheiro de software",
        "desenvolvedor backend",
        "desenvolvedor frontend",
        "desenvolvedor full stack",
        "desenvolvedor mobile",
        "desenvolvedor python",
        "desenvolvedor java",
        "desenvolvedor javascript",
        "desenvolvedor .net",
        "desenvolvedor php",
    ]
    assert settings.scrape_cron == "0 6 * * *"
    assert settings.scrape_timezone == "America/Sao_Paulo"
    assert settings.scrape_on_start is True
    assert settings.scrape_run_timeout_minutes == 60
    assert settings.job_inactive_after_days == 7
    assert settings.scrape_max_pages == 20
    assert settings.api_port == 8000
    assert settings.scrape_download_delay == 1.0
    assert settings.log_level == "INFO"
    assert (settings.postgres_user, settings.postgres_password, settings.postgres_db) == (
        "take_jobs",
        "take_jobs_dev",
        "take_jobs",
    )
    assert settings.database_url == (
        "postgresql+asyncpg://take_jobs:take_jobs_dev@db:5432/take_jobs"
    )
    assert settings.scrape_user_agent == "take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)"
    assert "full-stack" in settings.relevance_include_keywords
    assert len(settings.relevance_include_keywords) == 17
    assert settings.relevance_exclude_keywords[0] == "cnc"
    assert len(settings.relevance_exclude_keywords) == 12


def test_ut021_list_is_split_stripped_and_drops_empties(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_TERMS", " desenvolvedor python , ,desenvolvedor go ")

    assert make_settings().scrape_terms == ["desenvolvedor python", "desenvolvedor go"]


@pytest.mark.parametrize(
    ("terms", "named"),
    [
        ("python,Python", "'python', 'Python'"),
        ("desenvolvedor c#, desenvolvedor c++", "'desenvolvedor c#', 'desenvolvedor c++'"),
        ("desenvolvedor .net,desenvolvedor net", "'desenvolvedor .net', 'desenvolvedor net'"),
        ("Programação,programacao", "'Programação', 'programacao'"),
    ],
)
def test_ut118_terms_with_the_same_slug_are_rejected_naming_both(
    monkeypatch: pytest.MonkeyPatch, terms: str, named: str
) -> None:
    """UT-118 (review round 7, issue 002): both sites would get the same URL for the second term."""
    monkeypatch.setenv("SCRAPE_TERMS", terms)

    with pytest.raises(ValidationError, match="SCRAPE_TERMS") as raised:
        make_settings()

    assert named in str(raised.value)


def test_ut118_term_without_letters_or_digits_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """UT-118: an empty slug is rejected too."""
    monkeypatch.setenv("SCRAPE_TERMS", "python, ###")

    with pytest.raises(ValidationError, match=r"(?s)SCRAPE_TERMS.*no letters or digits"):
        make_settings()


def test_ut118_repeating_the_same_term_is_still_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """UT-118: the exact same term collapses into one combination, it is not a collision."""
    monkeypatch.setenv("SCRAPE_TERMS", "python, python")

    assert make_settings().scrape_terms == ["python", "python"]


@pytest.mark.parametrize("key", ["SCRAPE_TERMS", "RELEVANCE_INCLUDE_KEYWORDS"])
def test_ut022_empty_required_list_is_rejected(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv(key, "")

    with pytest.raises(ValidationError, match=key):
        make_settings()


def test_ut022_empty_exclude_list_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEVANCE_EXCLUDE_KEYWORDS", "")

    assert make_settings().relevance_exclude_keywords == []


@pytest.mark.parametrize("value", ["abc", "0"])
def test_ut023_invalid_max_pages(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("SCRAPE_MAX_PAGES", value)

    with pytest.raises(ValidationError, match="SCRAPE_MAX_PAGES"):
        make_settings()


def test_ut024_download_delay_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_DOWNLOAD_DELAY", "0.5")

    with pytest.raises(ValidationError, match="SCRAPE_DOWNLOAD_DELAY"):
        make_settings()


def test_ut025_invalid_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_CRON", "61 * * * *")

    with pytest.raises(ValidationError, match="SCRAPE_CRON"):
        make_settings()


@pytest.mark.parametrize("cron", ["0 6 * * 0", "0 6 * * 7", "0 6 * * 0-4", "0 6 * * sun-thu"])
def test_cron_accepts_standard_day_of_week(monkeypatch: pytest.MonkeyPatch, cron: str) -> None:
    monkeypatch.setenv("SCRAPE_CRON", cron)

    assert make_settings().scrape_cron == cron


def test_cron_rejects_day_of_week_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_CRON", "0 6 * * 8")

    with pytest.raises(ValidationError, match="SCRAPE_CRON"):
        make_settings()


def test_ut026_unknown_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_TIMEZONE", "Mars/Olympus")

    with pytest.raises(ValidationError, match="SCRAPE_TIMEZONE"):
        make_settings()


def test_ut027_run_timeout_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPE_RUN_TIMEOUT_MINUTES", "19")
    with pytest.raises(ValidationError, match="SCRAPE_RUN_TIMEOUT_MINUTES"):
        make_settings()

    monkeypatch.setenv("SCRAPE_RUN_TIMEOUT_MINUTES", "20")
    assert make_settings().scrape_run_timeout_minutes == 20


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("JOB_INACTIVE_AFTER_DAYS", "0"),
        ("LOG_LEVEL", "LOUD"),
        ("API_PORT", "70000"),
        ("SCRAPE_ON_START", "maybe"),
    ],
)
def test_other_invalid_values_name_the_key(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=key):
        make_settings()


def test_env_file_is_read_and_empty_value_is_not_replaced_by_default(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("RELEVANCE_EXCLUDE_KEYWORDS=\nLOG_LEVEL=debug\n")

    settings = Settings(_env_file=env_file)

    assert settings.relevance_exclude_keywords == []
    assert settings.log_level == "DEBUG"
