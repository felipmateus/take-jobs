"""PostgreSQL implementation of `CollectionRunRepository`."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Select, func, insert, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from take_jobs.domain.errors import RunAlreadyActiveError, RunTakenOverError
from take_jobs.domain.models import (
    CollectionRun,
    CombinationResult,
    Page,
    ResultStatus,
    RunStatus,
    RunTotals,
    RunTrigger,
)
from take_jobs.infrastructure.db.models import CollectionRunResultRow, CollectionRunRow

_INTERRUPTED = "interrupted"
_START_ATTEMPTS = 3


def _totals_subquery():
    return (
        select(
            CollectionRunResultRow.run_id.label("run_id"),
            func.sum(CollectionRunResultRow.new_count).label("new"),
            func.sum(CollectionRunResultRow.seen_again_count).label("seen_again"),
            func.sum(CollectionRunResultRow.discarded_count).label("discarded"),
        )
        .group_by(CollectionRunResultRow.run_id)
        .subquery("totals")
    )


def _runs_with_totals(*where: ColumnElement[bool]) -> Select:
    totals = _totals_subquery()
    return (
        select(
            CollectionRunRow,
            func.coalesce(totals.c.new, 0),
            func.coalesce(totals.c.seen_again, 0),
            func.coalesce(totals.c.discarded, 0),
        )
        .outerjoin(totals, totals.c.run_id == CollectionRunRow.id)
        .where(*where)
        .execution_options(populate_existing=True)
    )


def _to_run(
    row: CollectionRunRow,
    new: int,
    seen_again: int,
    discarded: int,
    results: tuple[CombinationResult, ...] = (),
) -> CollectionRun:
    return CollectionRun(
        id=row.id,
        trigger=RunTrigger(row.trigger),
        status=RunStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error,
        expected_combinations=row.expected_combinations,
        totals=RunTotals(new=int(new), seen_again=int(seen_again), discarded=int(discarded)),
        results=results,
    )


def _to_result(row: CollectionRunResultRow) -> CombinationResult:
    return CombinationResult(
        source=row.source,
        term=row.term,
        status=ResultStatus(row.status),
        pages=row.pages,
        new=row.new_count,
        seen_again=row.seen_again_count,
        discarded=row.discarded_count,
        error=row.error,
    )


class SqlAlchemyCollectionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self, trigger: RunTrigger, started_at: datetime, expected_combinations: int
    ) -> int:
        for _ in range(_START_ATTEMPTS):
            # Safety Invariant 1: the partial unique index is the guard; a conflict inserts nothing.
            result = await self._session.execute(
                pg_insert(CollectionRunRow)
                .values(
                    trigger=trigger.value,
                    status=RunStatus.RUNNING.value,
                    started_at=started_at,
                    expected_combinations=expected_combinations,
                )
                .on_conflict_do_nothing(
                    index_elements=[CollectionRunRow.status],
                    index_where=literal_column("status = 'running'"),
                )
                .returning(CollectionRunRow.id)
            )
            run_id = result.scalar_one_or_none()
            if run_id is not None:
                return run_id
            active = await self.get_active()
            if active is not None:
                raise RunAlreadyActiveError(active.id, active.started_at)
            # The other run finished between the conflict and the lookup: try again.
        raise RuntimeError("could not start a collection run: the running run keeps changing")

    async def get_active(self) -> CollectionRun | None:
        row = (
            await self._session.execute(
                _runs_with_totals(CollectionRunRow.status == RunStatus.RUNNING.value)
            )
        ).first()
        return _to_run(*row) if row is not None else None

    async def latest_finished(self) -> CollectionRun | None:
        row = (
            await self._session.execute(
                _runs_with_totals(CollectionRunRow.status != RunStatus.RUNNING.value)
                .order_by(CollectionRunRow.started_at.desc(), CollectionRunRow.id.desc())
                .limit(1)
            )
        ).first()
        return _to_run(*row) if row is not None else None

    async def mark_interrupted(self, run_id: int, finished_at: datetime) -> None:
        await self._leave_running(run_id, RunStatus.FAILED, finished_at, _INTERRUPTED)

    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        results: Sequence[CombinationResult],
        finished_at: datetime,
        error: str | None,
    ) -> None:
        if status is RunStatus.RUNNING:
            raise ValueError("finish needs a final status, not 'running'")
        # The conditional update comes first: a taken-over run gets no result rows.
        await self._leave_running(run_id, status, finished_at, error)
        if results:
            await self._session.execute(
                insert(CollectionRunResultRow),
                [
                    {
                        "run_id": run_id,
                        "source": result.source,
                        "term": result.term,
                        "status": result.status.value,
                        "pages": result.pages,
                        "new_count": result.new,
                        "seen_again_count": result.seen_again,
                        "discarded_count": result.discarded,
                        "error": result.error,
                    }
                    for result in results
                ],
            )

    async def get(self, run_id: int) -> CollectionRun | None:
        row = (
            await self._session.execute(_runs_with_totals(CollectionRunRow.id == run_id))
        ).first()
        if row is None:
            return None
        result_rows = await self._session.scalars(
            select(CollectionRunResultRow)
            .where(CollectionRunResultRow.run_id == run_id)
            .order_by(CollectionRunResultRow.id)
        )
        return _to_run(*row, results=tuple(_to_result(r) for r in result_rows))

    async def list(self, page: int, size: int) -> Page[CollectionRun]:
        total = await self._session.scalar(select(func.count()).select_from(CollectionRunRow))
        rows = await self._session.execute(
            _runs_with_totals()
            .order_by(CollectionRunRow.started_at.desc(), CollectionRunRow.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return Page(
            items=tuple(_to_run(*row) for row in rows),
            total=total or 0,
            page=page,
            size=size,
        )

    async def _leave_running(
        self, run_id: int, status: RunStatus, finished_at: datetime, error: str | None
    ) -> None:
        """Safety Invariant 2: leave `running` exactly once, or raise `RunTakenOverError`."""
        result = await self._session.execute(
            update(CollectionRunRow)
            .where(
                CollectionRunRow.id == run_id,
                CollectionRunRow.status == RunStatus.RUNNING.value,
            )
            .values(status=status.value, finished_at=finished_at, error=error)
            .returning(CollectionRunRow.id)
        )
        if result.scalar_one_or_none() is None:
            raise RunTakenOverError(run_id)
