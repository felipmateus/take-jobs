"""UT-056 to UT-064, UT-066 to UT-068: CollectionService over in-memory fakes."""

from datetime import timedelta

import pytest

from take_jobs.application.errors import RunAlreadyActiveError, RunTakenOverError
from take_jobs.application.services import CollectionService
from take_jobs.domain.models import (
    CombinationOutcome,
    ResultStatus,
    RunStatus,
    RunTotals,
    RunTrigger,
    ScrapedJob,
    ScrapeReport,
    Seniority,
)
from take_jobs.domain.rules import RelevancePolicy
from tests.fakes import NOW, FixedClock, InMemoryStore, InMemoryUnitOfWork

RUN_TIMEOUT = timedelta(minutes=60)


def make_service(store: InMemoryStore, clock: FixedClock | None = None) -> CollectionService:
    return CollectionService(
        lambda: InMemoryUnitOfWork(store),
        RelevancePolicy(
            include=["desenvolvedor", "dev", "programador"], exclude=["cnc", "suporte"]
        ),
        clock or FixedClock(NOW),
        RUN_TIMEOUT,
    )


def scraped(external_id: str, title: str, source: str = "vagas") -> ScrapedJob:
    return ScrapedJob(
        source=source,
        external_id=external_id,
        title=title,
        url=f"https://example.test/{source}/{external_id}",
        company="Acme",
        location="Recife - PE",
        description=None,
        published_label=None,
    )


def outcome(
    source: str, term: str, *jobs: ScrapedJob, pages: int = 1, error: str | None = None
) -> CombinationOutcome:
    return CombinationOutcome(source=source, term=term, jobs=jobs, pages=pages, error=error)


def start_running(store: InMemoryStore) -> int:
    return store.add_run(started_at=NOW - timedelta(minutes=1)).id


# --------------------------------------------------------------------------- start_run


async def test_ut056_start_run_creates_a_running_run() -> None:
    store = InMemoryStore()

    run_id = await make_service(store).start_run(RunTrigger.MANUAL, expected_combinations=24)

    (run,) = store.runs.values()
    assert run.id == run_id
    assert (run.status, run.trigger, run.expected_combinations, run.started_at) == (
        RunStatus.RUNNING,
        RunTrigger.MANUAL,
        24,
        NOW,
    )
    assert store.events[-1] == "commit"


async def test_ut057_live_active_run_refuses_a_new_one() -> None:
    store = InMemoryStore()
    active = store.add_run(started_at=NOW - timedelta(minutes=5))

    with pytest.raises(RunAlreadyActiveError) as raised:
        await make_service(store).start_run(RunTrigger.SCHEDULED, 24)

    assert raised.value.run_id == active.id
    assert raised.value.started_at == active.started_at
    assert list(store.runs) == [active.id]
    assert store.runs[active.id].status is RunStatus.RUNNING


async def test_ut058_stale_active_run_is_interrupted_then_a_new_run_starts() -> None:
    store = InMemoryStore()
    stale = store.add_run(started_at=NOW - timedelta(minutes=61))

    new_id = await make_service(store).start_run(RunTrigger.SCHEDULED, 24)

    interrupted = store.runs[stale.id]
    assert (interrupted.status, interrupted.error, interrupted.finished_at) == (
        RunStatus.FAILED,
        "interrupted",
        NOW,
    )
    assert store.runs[new_id].status is RunStatus.RUNNING
    assert store.events == ["mark_interrupted", "start", "commit"]


async def test_run_exactly_at_the_timeout_is_still_live() -> None:
    store = InMemoryStore()
    store.add_run(started_at=NOW - RUN_TIMEOUT)

    with pytest.raises(RunAlreadyActiveError):
        await make_service(store).start_run(RunTrigger.MANUAL, 24)


async def test_stale_run_ended_by_someone_else_meanwhile_does_not_fail_the_start() -> None:
    store = InMemoryStore()
    stale = store.add_run(started_at=NOW - timedelta(minutes=90))
    uow = InMemoryUnitOfWork(store)
    original = uow.runs.mark_interrupted

    async def lose_the_race(run_id: int, finished_at) -> None:
        await original(run_id, finished_at)  # the other process ends it first...
        await original(run_id, finished_at)  # ...so ours finds it already finished

    uow.runs.mark_interrupted = lose_the_race  # type: ignore[method-assign]
    service = CollectionService(
        lambda: uow, RelevancePolicy(include=["dev"], exclude=[]), FixedClock(NOW), RUN_TIMEOUT
    )

    new_id = await service.start_run(RunTrigger.STARTUP, 24)

    assert store.runs[stale.id].status is RunStatus.FAILED
    assert store.runs[new_id].status is RunStatus.RUNNING


# --------------------------------------------------------------------------- complete_run


async def test_ut059_complete_run_filters_classifies_upserts_and_counts() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    report = ScrapeReport(
        outcomes=(
            outcome(
                "vagas",
                "desenvolvedor python",
                scraped("1", "Desenvolvedor Python Sênior"),
                scraped("2", "Analista de Suporte"),
            ),
            outcome(
                "infojobs", "desenvolvedor python", scraped("9", "Dev Pleno", source="infojobs")
            ),
        )
    )

    run = await make_service(store).complete_run(run_id, report)

    upserts = [event for event in store.events if event.startswith("upsert:")]
    assert upserts == ["upsert:vagas/1", "upsert:infojobs/9"]
    assert {key: job.seniority for key, job in store.jobs.items()} == {
        ("vagas", "1"): Seniority.SENIOR,
        ("infojobs", "9"): Seniority.MID,
    }
    assert [
        (r.source, r.term, r.status, r.new, r.seen_again, r.discarded, r.error) for r in run.results
    ] == [
        ("vagas", "desenvolvedor python", ResultStatus.SUCCESS, 1, 0, 1, None),
        ("infojobs", "desenvolvedor python", ResultStatus.SUCCESS, 1, 0, 0, None),
    ]
    assert (run.status, run.finished_at, run.error) == (RunStatus.SUCCESS, NOW, None)
    assert run.totals == RunTotals(new=2, seen_again=0, discarded=1)
    assert store.runs[run_id] == run


async def test_ut060_job_new_in_one_combination_is_seen_again_in_the_next() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    same = scraped("1", "Desenvolvedor Go")
    report = ScrapeReport(
        outcomes=(
            outcome("vagas", "desenvolvedor", same),
            outcome("vagas", "programador", same),
        )
    )

    run = await make_service(store).complete_run(run_id, report)

    assert [(r.new, r.seen_again) for r in run.results] == [(1, 0), (0, 1)]
    assert len(store.jobs) == 1


async def test_job_stored_by_an_earlier_run_counts_as_seen_again_and_is_refreshed() -> None:
    store = InMemoryStore()
    earlier = store.add_job(scraped("1", "Desenvolvedor Go"), seen_at=NOW - timedelta(days=2))
    run_id = start_running(store)
    report = ScrapeReport(
        outcomes=(outcome("vagas", "desenvolvedor", scraped("1", "Desenvolvedor Go Junior")),)
    )

    run = await make_service(store).complete_run(run_id, report)

    assert [(r.new, r.seen_again) for r in run.results] == [(0, 1)]
    refreshed = store.jobs[("vagas", "1")]
    assert refreshed.first_seen_at == earlier.first_seen_at
    assert (refreshed.last_seen_at, refreshed.seniority) == (NOW, Seniority.JUNIOR)


async def test_ut061_failed_combination_keeps_its_jobs_and_the_run_is_partial() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    report = ScrapeReport(
        outcomes=(
            outcome(
                "vagas",
                "a",
                scraped("1", "Dev Python"),
                scraped("2", "Dev Java"),
                pages=2,
            ),
            outcome(
                "infojobs",
                "a",
                scraped("7", "Dev Go", source="infojobs"),
                pages=3,
                error="HTTP 403 Forbidden",
            ),
        )
    )

    run = await make_service(store).complete_run(run_id, report)

    assert ("infojobs", "7") in store.jobs
    failed = run.results[1]
    assert (failed.status, failed.pages, failed.new, failed.error) == (
        ResultStatus.FAILED,
        3,
        1,
        "HTTP 403 Forbidden",
    )
    assert run.status is RunStatus.PARTIAL


async def test_ut062_every_combination_failed_makes_the_run_failed() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    report = ScrapeReport(
        outcomes=(
            outcome("vagas", "a", pages=0, error="boom"),
            outcome("infojobs", "a", pages=0, error="blocked by robots.txt"),
        )
    )

    run = await make_service(store).complete_run(run_id, report)

    assert run.status is RunStatus.FAILED
    assert run.error is None
    assert len(run.results) == 2


async def test_empty_report_finishes_failed_with_no_results() -> None:
    store = InMemoryStore()
    run_id = start_running(store)

    run = await make_service(store).complete_run(run_id, ScrapeReport(outcomes=()))

    assert (run.status, run.results, run.totals) == (RunStatus.FAILED, (), RunTotals(0, 0, 0))


async def test_ut064_stored_job_whose_title_became_irrelevant_is_not_refreshed() -> None:
    store = InMemoryStore()
    old = NOW - timedelta(days=3)
    store.add_job(scraped("1", "Desenvolvedor Go"), seen_at=old)
    run_id = start_running(store)
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Programador de CNC")),))

    run = await make_service(store).complete_run(run_id, report)

    assert not [event for event in store.events if event.startswith("upsert:")]
    assert [(r.new, r.seen_again, r.discarded) for r in run.results] == [(0, 0, 1)]
    assert store.jobs[("vagas", "1")].last_seen_at == old
    assert store.jobs[("vagas", "1")].title == "Desenvolvedor Go"


async def test_complete_run_on_a_finished_or_missing_run_is_taken_over() -> None:
    store = InMemoryStore()
    done = store.add_run(started_at=NOW, status=RunStatus.FAILED, error="interrupted")
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Dev Go")),))

    for run_id in (done.id, 999):
        with pytest.raises(RunTakenOverError):
            await make_service(store).complete_run(run_id, report)

    assert not store.jobs
    assert not [event for event in store.events if event.startswith("upsert:")]


async def test_ut066_run_taken_over_at_finish_propagates_and_rolls_back() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    store.finish_error = RunTakenOverError(run_id)
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Dev Go")),))

    with pytest.raises(RunTakenOverError):
        await make_service(store).complete_run(run_id, report)

    assert store.jobs == {}
    assert store.runs[run_id].status is RunStatus.RUNNING
    assert store.events[-1] == "rollback"


async def test_upsert_failure_rolls_back_and_skips_before_commit() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    store.upsert_error = RuntimeError("db gone")
    called: list[str] = []
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Dev Go")),))

    with pytest.raises(RuntimeError, match="db gone"):
        await make_service(store).complete_run(
            run_id, report, before_commit=lambda: called.append("hook")
        )

    assert called == []
    assert store.events[-1] == "rollback"


async def test_ut068_before_commit_runs_last_inside_the_unit_of_work() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    report = ScrapeReport(
        outcomes=(
            outcome("vagas", "a", scraped("1", "Dev Go"), scraped("2", "Dev Java")),
            outcome("infojobs", "a", scraped("3", "Dev Rust", source="infojobs")),
        )
    )

    await make_service(store).complete_run(
        run_id, report, before_commit=lambda: store.events.append("before_commit")
    )

    assert store.events == [
        "upsert:vagas/1",
        "upsert:vagas/2",
        "upsert:infojobs/3",
        "finish",
        "before_commit",
        "commit",
    ]


async def test_ut068_before_commit_is_not_called_when_finish_raises() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    store.finish_error = RunTakenOverError(run_id)
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Dev Go")),))

    with pytest.raises(RunTakenOverError):
        await make_service(store).complete_run(
            run_id, report, before_commit=lambda: store.events.append("before_commit")
        )

    assert "before_commit" not in store.events
    assert store.events[-1] == "rollback"


async def test_ut068_without_before_commit_behaves_the_same() -> None:
    store = InMemoryStore()
    run_id = start_running(store)
    report = ScrapeReport(outcomes=(outcome("vagas", "a", scraped("1", "Dev Go")),))

    run = await make_service(store).complete_run(run_id, report, before_commit=None)

    assert run.status is RunStatus.SUCCESS
    assert store.events == ["upsert:vagas/1", "finish", "commit"]


# --------------------------------------------------------------------------- fail_run / get_run


async def test_ut063_fail_run_records_the_error_with_no_results() -> None:
    store = InMemoryStore()
    run_id = start_running(store)

    run = await make_service(store).fail_run(run_id, "crawler crashed: exit code 1")

    assert (run.status, run.error, run.results, run.finished_at) == (
        RunStatus.FAILED,
        "crawler crashed: exit code 1",
        (),
        NOW,
    )
    assert store.runs[run_id] == run


async def test_fail_run_on_a_finished_run_raises_taken_over() -> None:
    store = InMemoryStore()
    done = store.add_run(started_at=NOW, status=RunStatus.SUCCESS)

    with pytest.raises(RunTakenOverError):
        await make_service(store).fail_run(done.id, "late")

    assert store.runs[done.id].status is RunStatus.SUCCESS


async def test_get_run_returns_the_run_or_none() -> None:
    store = InMemoryStore()
    run = store.add_run(started_at=NOW)
    service = make_service(store)

    assert await service.get_run(run.id) == run
    assert await service.get_run(404) is None


# --------------------------------------------------------------------------- startup_reason / ping


async def test_ut067_startup_reason_for_an_empty_store() -> None:
    store = InMemoryStore(empty=True)

    assert await make_service(store).startup_reason() == "empty_job_store"


async def test_ut067_startup_reason_when_the_latest_run_is_old() -> None:
    store = InMemoryStore(empty=False)
    store.add_run(started_at=NOW - timedelta(hours=25), status=RunStatus.SUCCESS)

    assert await make_service(store).startup_reason() == "no_recent_run"


async def test_ut067_startup_reason_none_when_a_recent_run_finished() -> None:
    store = InMemoryStore(empty=False)
    store.add_run(started_at=NOW - timedelta(hours=2), status=RunStatus.FAILED)

    assert await make_service(store).startup_reason() is None


async def test_ut067_startup_reason_ignores_a_running_run() -> None:
    store = InMemoryStore(empty=False)
    store.add_run(started_at=NOW - timedelta(hours=1))

    assert await make_service(store).startup_reason() == "no_recent_run"


async def test_ut067_ping_calls_the_probe_once() -> None:
    store = InMemoryStore()

    await make_service(store).ping()

    assert store.ping_calls == 1


async def test_ut067_ping_propagates_the_probe_error() -> None:
    store = InMemoryStore(ping_error=ConnectionRefusedError("down"))

    with pytest.raises(ConnectionRefusedError):
        await make_service(store).ping()

    assert store.events[-1] == "rollback"
