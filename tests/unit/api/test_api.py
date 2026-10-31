"""UT-090 to UT-103 and the DI chain: the real app with the services and the probe overridden."""

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Annotated, Any

import pytest
from fastapi import Depends
from sqlalchemy.exc import InterfaceError, OperationalError

from take_jobs.api.dependencies import get_session, get_settings
from take_jobs.application.errors import (
    CollectionRunNotFoundError,
    InvalidPeriodError,
    JobNotFoundError,
)
from take_jobs.config import Settings
from take_jobs.domain.models import RunStatus, RunTotals, Seniority
from take_jobs.infrastructure.scraping.registry import SOURCES
from tests.unit.api.conftest import Rig, make_job, make_run

JOB_KEYS = {
    "id",
    "title",
    "company",
    "location",
    "description",
    "published_label",
    "source",
    "url",
    "seniority",
    "first_seen_at",
    "last_seen_at",
    "active",
}


def test_ut090_search_defaults(rig: Rig) -> None:
    response = rig.client().get("/jobs")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "size", "pages"}
    assert (body["total"], body["page"], body["size"], body["pages"]) == (1, 1, 20, 1)
    assert set(body["items"][0]) == JOB_KEYS
    assert body["items"][0]["first_seen_at"] == "2026-10-30T19:12:44Z"
    assert body["items"][0]["seniority"] == "senior"
    query = rig.jobs.queries[0]
    assert (query.page, query.size, query.include_inactive) == (1, 20, False)
    assert (query.q, query.location, query.seen_from, query.seen_to) == (None,) * 4
    assert (query.sources, query.seniorities) == (frozenset(), frozenset())


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("size=0", "size"),
        ("size=101", "size"),
        ("page=0", "page"),
        ("page=99999999999999999999", "page"),
        ("seen_from=31/10/2026", "seen_from"),
    ],
)
def test_ut091_invalid_parameters_are_validation_errors(rig: Rig, query: str, field: str) -> None:
    response = rig.client().get(f"/jobs?{query}")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Invalid request parameters."
    assert error["details"][0]["field"] == field
    assert rig.jobs.queries == []


def test_ut091_size_message_matches_the_documented_example(rig: Rig) -> None:
    body = rig.client().get("/jobs?size=500").json()

    assert body == {
        "error": {
            "code": "validation_error",
            "message": "Invalid request parameters.",
            "details": [{"field": "size", "message": "Input should be less than or equal to 100"}],
        }
    }


def test_validation_error_has_one_detail_per_invalid_field(rig: Rig) -> None:
    body = rig.client().get("/jobs?size=0&page=0&source=x&source=y").json()

    assert sorted(d["field"] for d in body["error"]["details"]) == ["page", "size", "source"]


def test_ut092_invalid_period(rig: Rig) -> None:
    rig.jobs.error = InvalidPeriodError(date(2026, 10, 20), date(2026, 10, 1))

    response = rig.client().get("/jobs?seen_from=2026-10-20&seen_to=2026-10-01")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_period",
            "message": "seen_from (2026-10-20) must be on or before seen_to (2026-10-01).",
            "details": [],
        }
    }
    assert rig.jobs.queries[0].seen_from == date(2026, 10, 20)
    assert rig.jobs.queries[0].seen_to == date(2026, 10, 1)


def test_ut093_unknown_source(rig: Rig) -> None:
    response = rig.client().get("/jobs?source=linkedin")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [d["field"] for d in error["details"]] == ["source"]


def test_ut094_unknown_seniority(rig: Rig) -> None:
    response = rig.client().get("/jobs?seniority=lead")

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["seniority"]


def test_ut095_query_longer_than_100_characters(rig: Rig) -> None:
    ok = rig.client().get("/jobs", params={"q": "a" * 100})
    response = rig.client().get("/jobs", params={"q": "a" * 101})

    assert ok.status_code == 200
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [d["field"] for d in error["details"]] == ["q"]


def test_ut096_job_detail(rig: Rig) -> None:
    ok = rig.client().get("/jobs/812")
    rig.jobs.error = JobNotFoundError(999999)
    missing = rig.client().get("/jobs/999999")
    not_an_id = rig.client().get("/jobs/abc")

    assert ok.status_code == 200
    assert set(ok.json()) == JOB_KEYS
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "job_not_found", "message": "Job 999999 was not found.", "details": []}
    }
    assert not_an_id.status_code == 422
    assert not_an_id.json()["error"]["details"][0]["field"] == "job_id"


def test_inactive_job_is_returned_with_active_false(rig: Rig) -> None:
    rig.jobs.jobs = [make_job(active=False)]

    assert rig.client().get("/jobs/812").json()["active"] is False


def test_ut097_unknown_run(rig: Rig) -> None:
    rig.runs.error = CollectionRunNotFoundError(404)

    response = rig.client().get("/collection-runs/404")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "collection_run_not_found",
            "message": "Collection run 404 was not found.",
            "details": [],
        }
    }
    assert rig.client().get("/collection-runs/abc").status_code == 422


def test_ut098_unknown_route(rig: Rig) -> None:
    response = rig.client().get("/nope")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == []


def test_wrong_method_uses_the_error_shape(rig: Rig) -> None:
    response = rig.client().post("/jobs")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, ConnectionRefusedError("refused")),
        InterfaceError("SELECT 1", {}, ConnectionResetError("reset")),
        ConnectionRefusedError("refused"),
        TimeoutError("pool"),
    ],
    ids=["operational", "interface", "refused", "timeout"],
)
def test_ut099_database_errors_are_503(rig: Rig, error: Exception) -> None:
    rig.jobs.error = error
    rig.runs.error = error

    for path in ("/jobs", "/jobs/1", "/collection-runs", "/collection-runs/1"):
        response = rig.client().get(path)
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "database_unavailable",
                "message": "The database is unavailable. Try again later.",
                "details": [],
            }
        }


def test_ut100_unexpected_failure_is_500_without_details(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.jobs.error = RuntimeError("secret detail")

    with caplog.at_level(logging.ERROR, logger="take_jobs.api"):
        response = rig.client(raise_server_exceptions=False).get("/jobs")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": [],
        }
    }
    assert "secret detail" not in response.text
    record = next(r for r in caplog.records if "api_unhandled_error" in r.getMessage())
    assert record.exc_info is not None
    assert "secret detail" in str(record.exc_info[1])


def test_ut101_health_ok(rig: Rig) -> None:
    response = rig.client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert rig.probe.pings == 1


def test_ut101_health_unreachable(rig: Rig) -> None:
    rig.probe.error = OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))

    response = rig.client().get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}


def test_ut101_health_gives_up_after_three_seconds(rig: Rig) -> None:
    rig.probe.sleep_s = 5

    started = time.monotonic()
    response = rig.client().get("/health")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
    assert 2.9 <= elapsed < 3.5


def test_ut102_openapi_lists_exactly_the_routes_with_their_errors(rig: Rig) -> None:
    document = rig.client().get("/openapi.json").json()

    assert set(document["paths"]) == {
        "/jobs",
        "/jobs/{job_id}",
        "/collection-runs",
        "/collection-runs/{run_id}",
        "/health",
    }
    expected_errors = {
        ("/jobs", "get"): {"422", "503"},
        ("/jobs/{job_id}", "get"): {"404", "422", "503"},
        ("/collection-runs", "get"): {"422", "503"},
        ("/collection-runs/{run_id}", "get"): {"404", "422", "503"},
        ("/health", "get"): {"503"},
    }
    for (path, method), codes in expected_errors.items():
        responses = document["paths"][path][method]["responses"]
        assert set(responses) == {"200"} | codes
        for code in codes - {"503"} | ({"503"} if path != "/health" else set()):
            ref = responses[code]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorOut")
    health_503 = document["paths"]["/health"]["get"]["responses"]["503"]
    assert health_503["content"]["application/json"]["schema"]["$ref"].endswith("/HealthOut")


def test_ut102_source_enum_comes_from_the_injected_registry(
    build_rig: Callable[..., Rig],
) -> None:
    default = build_rig().client().get("/openapi.json").json()
    extended = {**SOURCES, "fakeboard": replace(SOURCES["vagas"], id="fakeboard")}
    rig = build_rig(extended)

    document = rig.client().get("/openapi.json").json()

    def source_enum(doc: dict[str, Any]) -> list[str]:
        parameter = next(
            p for p in doc["paths"]["/jobs"]["get"]["parameters"] if p["name"] == "source"
        )
        schema = parameter["schema"]
        items = next(s for s in schema.get("anyOf", [schema]) if s.get("type") == "array")["items"]
        return items["enum"]

    assert source_enum(default) == ["infojobs", "vagas"]
    assert source_enum(document) == ["fakeboard", "infojobs", "vagas"]
    assert rig.client().get("/jobs?source=fakeboard").status_code == 200
    assert rig.jobs.queries[0].sources == frozenset({"fakeboard"})
    assert rig.client().get("/docs").status_code == 200
    assert "text/html" in rig.client().get("/docs").headers["content-type"]


def test_ut103_repeated_parameters_reach_the_service(rig: Rig) -> None:
    response = rig.client().get(
        "/jobs?source=vagas&source=infojobs&seniority=senior&seniority=mid&location=Sao%20Paulo"
    )

    assert response.status_code == 200
    query = rig.jobs.queries[0]
    assert query.sources == frozenset({"vagas", "infojobs"})
    assert query.seniorities == frozenset({Seniority.SENIOR, Seniority.MID})
    assert query.location == "Sao Paulo"


def test_filters_reach_the_service_and_blank_text_means_absent(rig: Rig) -> None:
    rig.client().get(
        "/jobs?q=%20%20python%20&location=%20%20&include_inactive=true&page=3&size=5"
        "&seen_from=2026-10-01&seen_to=2026-10-20"
    )

    query = rig.jobs.queries[0]
    assert (query.q, query.location) == ("python", None)
    assert (query.include_inactive, query.page, query.size) == (True, 3, 5)
    assert (query.seen_from, query.seen_to) == (date(2026, 10, 1), date(2026, 10, 20))


def test_pages_come_from_the_total(rig: Rig) -> None:
    rig.jobs.jobs = [make_job(i) for i in range(1, 4)]

    body = rig.client().get("/jobs?size=2").json()

    assert (body["total"], body["size"], body["pages"], len(body["items"])) == (3, 2, 2, 3)


def test_run_list_and_detail_shapes(rig: Rig) -> None:
    running = make_run(
        10, status=RunStatus.RUNNING, finished_at=None, totals=RunTotals(0, 0, 0), results=()
    )
    rig.runs.runs = [running, make_run()]

    listing = rig.client().get("/collection-runs?size=2").json()

    assert rig.runs.calls == [(1, 2)]
    assert set(listing) == {"items", "total", "page", "size", "pages"}
    assert set(listing["items"][0]) == {
        "id",
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "error",
        "totals",
    }
    assert listing["items"][0]["finished_at"] is None
    assert listing["items"][0]["totals"] == {"new": 0, "seen_again": 0, "discarded": 0}

    rig.runs.runs = [running]
    assert rig.client().get("/collection-runs/10").json()["results"] == []

    rig.runs.runs = [make_run()]
    detail = rig.client().get("/collection-runs/9").json()
    assert detail["totals"] == {"new": 4, "seen_again": 1801, "discarded": 391}
    assert detail["results"] == [
        {
            "source": "vagas",
            "term": "desenvolvedor",
            "status": "success",
            "pages": 20,
            "new": 1,
            "seen_again": 759,
            "discarded": 40,
            "error": None,
        }
    ]


@pytest.mark.parametrize("query", ["page=0", "page=1000000001", "size=0", "size=101"])
def test_run_list_validates_page_and_size(rig: Rig, query: str) -> None:
    response = rig.client().get(f"/collection-runs?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_settings_come_from_the_app_not_from_a_process_global(
    build_rig: Callable[..., Rig],
) -> None:
    rigs = [build_rig(), build_rig()]
    for rig, days in zip(rigs, (3, 9), strict=True):
        rig.app.state.settings = Settings(_env_file=None, job_inactive_after_days=days)

        @rig.app.get("/probe-settings")
        async def probe(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, int]:
            return {"days": settings.job_inactive_after_days}

    assert [rig.client().get("/probe-settings").json()["days"] for rig in rigs] == [3, 9]


class FakeEngine:
    def __init__(self, url: str) -> None:
        self.url = url
        self.disposed = 0

    async def dispose(self) -> None:
        self.disposed += 1


def test_lifespan_creates_the_engine_and_disposes_it_on_shutdown(
    build_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    engines: list[FakeEngine] = []

    def make_engine(url: str) -> FakeEngine:
        engines.append(FakeEngine(url))
        return engines[-1]

    monkeypatch.setattr("take_jobs.api.app.make_engine", make_engine)
    monkeypatch.setattr(
        "take_jobs.api.app.make_sessionmaker", lambda engine: ("sessionmaker", engine)
    )
    rig = build_rig()
    rig.app.state.settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://u:take_jobs_dev@h/d"
    )

    assert engines == []
    with rig.client() as client:
        assert [e.url for e in engines] == ["postgresql+asyncpg://u:take_jobs_dev@h/d"]
        assert engines[0].disposed == 0
        assert client.app.state.sessionmaker == ("sessionmaker", engines[0])  # type: ignore[attr-defined]

    assert engines[0].disposed == 1


def test_every_request_gets_its_own_session(build_rig: Callable[..., Rig]) -> None:
    events: list[tuple[str, int]] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            events.append(("open", id(self)))
            return self

        async def __aexit__(self, *exc: object) -> None:
            events.append(("close", id(self)))

    rig = build_rig()
    rig.app.state.sessionmaker = FakeSession

    @rig.app.get("/probe-session")
    async def probe(session: Annotated[Any, Depends(get_session)]) -> dict[str, int]:
        return {"session": id(session)}

    client = rig.client()  # no lifespan: the sessionmaker above stays in place
    client.get("/probe-session")
    client.get("/probe-session")

    opens = [i for kind, i in events if kind == "open"]
    closes = [i for kind, i in events if kind == "close"]
    assert len(opens) == 2
    assert sorted(opens) == sorted(closes)
