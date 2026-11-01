"""Application settings, read from the environment (then `.env`).

Every key and default comes from `_dx.md` > Config. Fields use the upper-case environment name
as validation alias, so a `ValidationError` always names the offending key (for example
`SCRAPE_MAX_PAGES`), which the CLI maps to `Invalid configuration: <KEY>: <reason>`.
"""

import logging
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from take_jobs.domain.rules import normalize, to_standard_crontab

DEFAULT_SCRAPE_TERMS = [
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

DEFAULT_RELEVANCE_INCLUDE_KEYWORDS = [
    "desenvolvedor",
    "desenvolvedora",
    "developer",
    "programador",
    "programadora",
    "programmer",
    "engenheiro de software",
    "engenheira de software",
    "software engineer",
    "dev",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "full stack",
    "fullstack",
    "full-stack",
]

DEFAULT_RELEVANCE_EXCLUDE_KEYWORDS = [
    "cnc",
    "torno",
    "usinagem",
    "producao",
    "pcp",
    "manutencao",
    "negocios",
    "vendas",
    "comercial",
    "textil",
    "moda",
    "costura",
    "transporte",
    "transportes",
    "cargas",
    "programador de logistica",
    "laser",
    "plasma",
    "puncionadeira",
    "dobradeira",
    "corte",
    "dobra",
    "comando numerico",
    "materiais",
    "programador visual",
    "programador de servicos",
    "programador operacional",
    "rotas",
    "frota",
    "mao de obra",
    "nesting",
    "bordado",
    "cad",
    "injetora",
    "eletricista",
    "clp",
    "plc",
    "bordados",
    "fornecedores",
    "carteira de clientes",
    "vendedor",
    "vendedora",
    "programador de ligacao",
]

_LOG_LEVEL_NAMES = frozenset(logging.getLevelNamesMapping())

# Comma-separated list, split by `_split_csv`; `NoDecode` stops pydantic-settings from
# trying to parse the raw value as JSON first.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias="API_PORT")

    postgres_user: str = Field(default="take_jobs", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="take_jobs_dev", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="take_jobs", validation_alias="POSTGRES_DB")
    database_url: str = Field(
        default="postgresql+asyncpg://take_jobs:take_jobs_dev@db:5432/take_jobs",
        validation_alias="DATABASE_URL",
    )

    scrape_cron: str = Field(default="0 6 * * *", validation_alias="SCRAPE_CRON")
    scrape_timezone: str = Field(default="America/Sao_Paulo", validation_alias="SCRAPE_TIMEZONE")
    scrape_on_start: bool = Field(default=True, validation_alias="SCRAPE_ON_START")
    scrape_run_timeout_minutes: int = Field(
        default=60, ge=20, validation_alias="SCRAPE_RUN_TIMEOUT_MINUTES"
    )

    scrape_terms: CsvList = Field(
        default_factory=lambda: list(DEFAULT_SCRAPE_TERMS), validation_alias="SCRAPE_TERMS"
    )

    scrape_max_pages: int = Field(default=20, ge=1, validation_alias="SCRAPE_MAX_PAGES")
    scrape_download_delay: float = Field(
        default=1.0, ge=1.0, validation_alias="SCRAPE_DOWNLOAD_DELAY"
    )
    scrape_user_agent: str = Field(
        default="take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)",
        validation_alias="SCRAPE_USER_AGENT",
    )

    relevance_include_keywords: CsvList = Field(
        default_factory=lambda: list(DEFAULT_RELEVANCE_INCLUDE_KEYWORDS),
        validation_alias="RELEVANCE_INCLUDE_KEYWORDS",
    )
    relevance_exclude_keywords: CsvList = Field(
        default_factory=lambda: list(DEFAULT_RELEVANCE_EXCLUDE_KEYWORDS),
        validation_alias="RELEVANCE_EXCLUDE_KEYWORDS",
    )

    job_inactive_after_days: int = Field(
        default=7, ge=1, validation_alias="JOB_INACTIVE_AFTER_DAYS"
    )

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator(
        "scrape_terms",
        "relevance_include_keywords",
        "relevance_exclude_keywords",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("scrape_terms", "relevance_include_keywords")
    @classmethod
    def _not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("scrape_terms")
    @classmethod
    def _distinct_slugs(cls, value: list[str]) -> list[str]:
        # Both sites build the listing URL from the normalized term (rule 4), so terms that only
        # differ in case, accents or punctuation (`python`/`Python`, `c#`/`c++`) would request the
        # same URL; Scrapy drops the second one and its combination would never run.
        by_slug: dict[str, list[str]] = {}
        for term in dict.fromkeys(value):
            slug = normalize(term)
            if not slug:
                raise ValueError(f"term {term!r} has no letters or digits")
            by_slug.setdefault(slug, []).append(term)
        for slug, terms in by_slug.items():
            if len(terms) > 1:
                names = ", ".join(repr(term) for term in terms)
                raise ValueError(f"terms {names} all search for {slug!r}; keep only one")
        return value

    @field_validator("scrape_cron")
    @classmethod
    def _valid_cron(cls, value: str) -> str:
        # Day-of-week follows standard cron (0 and 7 = Sunday); APScheduler's own numbering is
        # Monday-first, so the field is expanded into day names first.
        try:
            CronTrigger.from_crontab(to_standard_crontab(value))
        except ValueError as exc:
            raise ValueError(f"not a valid 5-field cron expression: {exc}") from exc
        return value

    @field_validator("scrape_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVEL_NAMES:
            raise ValueError(f"must be one of {', '.join(sorted(_LOG_LEVEL_NAMES))}")
        return level
