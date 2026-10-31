"""Fixtures for the API unit tests: the real app, with its services and probe overridden."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from take_jobs.api.app import create_app
from take_jobs.api.dependencies import (
    get_job_query_service,
    get_job_store_probe,
    get_run_query_service,
)
from take_jobs.application.queries import JobQuery, JobView
from take_jobs.config import Settings
from take_jobs.domain.models import (
    CollectionRun,
    CombinationResult,
    Job,
    Page,
    ResultStatus,
    RunStatus,
    RunTotals,
    RunTrigger,
    Seniority,
)

WHEN = datetime(2026, 10, 30, 19, 12, 44, tzinfo=UTC)


def make_job(job_id: int = 812, **overrides: Any) -> JobView:
    fields: dict[str, Any] = {
        "id": job_id,
        "source": "infojobs",
        "external_id": "11911899",
        "title": "Desenvolvedor Python Sênior",
        "url": "https://example.test/vaga",
        "company": "ISLA",
        "location": "Porto Alegre - RS",
        "description": "Responsabilidades: APIs REST.",
        "published_label": "28 out",
        "seniority": Seniority.SENIOR,
        "first_seen_at": WHEN,
        "last_seen_at": WHEN,
    }
    fields.update(overrides)
    active = fields.pop("active", True)
    return JobView.of(Job(**fields), active=active)


def make_run(run_id: int = 9, **overrides: Any) -> CollectionRun:
    fields: dict[str, Any] = {
        "id": run_id,
        "trigger": RunTrigger.MANUAL,
        "status": RunStatus.SUCCESS,
        "started_at": WHEN,
        "finished_at": WHEN,
        "error": None,
        "expected_combinations": 1,
        "totals": RunTotals(4, 1801, 391),
        "results": (
            CombinationResult("vagas", "desenvolvedor", ResultStatus.SUCCESS, 20, 1, 759, 40, None),
        ),
    }
    fields.update(overrides)
    return CollectionRun(**fields)


@dataclass
class FakeJobService:
    jobs: list[JobView] = field(default_factory=lambda: [make_job()])
    error: Exception | None = None
    queries: list[JobQuery] = field(default_factory=list)

    async def search(self, query: JobQuery) -> Page[JobView]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return Page(items=tuple(self.jobs), total=len(self.jobs), page=query.page, size=query.size)

    async def get(self, job_id: int) -> JobView:
        if self.error is not None:
            raise self.error
        return self.jobs[0]


@dataclass
class FakeRunService:
    runs: list[CollectionRun] = field(default_factory=lambda: [make_run()])
    error: Exception | None = None
    calls: list[tuple[int, int]] = field(default_factory=list)

    async def list(self, page: int, size: int) -> Page[CollectionRun]:
        self.calls.append((page, size))
        if self.error is not None:
            raise self.error
        return Page(items=tuple(self.runs), total=len(self.runs), page=page, size=size)

    async def get(self, run_id: int) -> CollectionRun:
        if self.error is not None:
            raise self.error
        return self.runs[0]


@dataclass
class FakeProbe:
    error: Exception | None = None
    sleep_s: float = 0.0
    pings: int = 0

    async def is_empty(self) -> bool:
        return False

    async def ping(self) -> None:
        self.pings += 1
        if self.sleep_s:
            await asyncio.sleep(self.sleep_s)
        if self.error is not None:
            raise self.error


@dataclass
class Rig:
    app: FastAPI
    jobs: FakeJobService
    runs: FakeRunService
    probe: FakeProbe

    def client(self, **kwargs: Any) -> TestClient:
        return TestClient(self.app, **kwargs)


@pytest.fixture
def build_rig() -> Callable[..., Rig]:
    def build(sources: Any = None) -> Rig:
        jobs, runs, probe = FakeJobService(), FakeRunService(), FakeProbe()
        app = create_app(Settings(_env_file=None), sources)
        app.dependency_overrides[get_job_query_service] = lambda: jobs
        app.dependency_overrides[get_run_query_service] = lambda: runs
        app.dependency_overrides[get_job_store_probe] = lambda: probe
        return Rig(app, jobs, runs, probe)

    return build


@pytest.fixture
def rig(build_rig: Callable[..., Rig]) -> Rig:
    return build_rig()
