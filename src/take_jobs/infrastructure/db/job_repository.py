"""PostgreSQL implementation of `JobRepository`."""

from datetime import datetime

from sqlalchemy import ColumnElement, String, and_, cast, func, literal_column, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from take_jobs.domain.models import Job, JobSearchCriteria, Page, ScrapedJob, Seniority
from take_jobs.infrastructure.db.models import JobRow

_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Make `%`, `_` and the escape character itself match literally in a LIKE pattern."""
    return (
        value.replace(_ESCAPE, _ESCAPE * 2).replace("%", f"{_ESCAPE}%").replace("_", f"{_ESCAPE}_")
    )


def _contains(column: ColumnElement[str], text: str) -> ColumnElement[bool]:
    """Accent- and case-insensitive substring match, literal for any user input (rule 19)."""
    normalized = func.immutable_unaccent(func.lower(cast(escape_like(text), String)))
    wildcard = literal_column("'%'", String)
    return column.like(wildcard.concat(normalized).concat(wildcard), escape=_ESCAPE)


def _to_job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        source=row.source,
        external_id=row.external_id,
        title=row.title,
        url=row.url,
        company=row.company,
        location=row.location,
        description=row.description,
        published_label=row.published_label,
        seniority=Seniority(row.seniority) if row.seniority is not None else None,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
    )


def _conditions(criteria: JobSearchCriteria) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if criteria.text:
        conditions.append(_contains(JobRow.search_text, criteria.text))
    if criteria.sources:
        conditions.append(JobRow.source.in_(sorted(criteria.sources)))
    if criteria.location:
        conditions.append(
            _contains(func.immutable_unaccent(func.lower(JobRow.location)), criteria.location)
        )
    if criteria.seniorities:
        conditions.append(JobRow.seniority.in_(sorted(s.value for s in criteria.seniorities)))
    # Rule 21: the job's seen interval [first_seen_at, last_seen_at] overlaps the period.
    if criteria.seen_from is not None:
        conditions.append(JobRow.last_seen_at >= criteria.seen_from)
    if criteria.seen_to is not None:
        conditions.append(JobRow.first_seen_at <= criteria.seen_to)
    if criteria.active_since is not None:
        conditions.append(JobRow.last_seen_at >= criteria.active_since)
    return conditions


class SqlAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, job: ScrapedJob, seniority: Seniority | None, seen_at: datetime) -> bool:
        values = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description,
            "published_label": job.published_label,
            "url": job.url,
            "seniority": seniority.value if seniority is not None else None,
        }
        statement = insert(JobRow).values(
            source=job.source,
            external_id=job.external_id,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            **values,
        )
        # Safety Invariant 4: `first_seen_at` is deliberately absent from the SET list.
        statement = statement.on_conflict_do_update(
            index_elements=[JobRow.source, JobRow.external_id],
            set_={
                **{name: getattr(statement.excluded, name) for name in values},
                "last_seen_at": statement.excluded.last_seen_at,
            },
        ).returning(literal_column("(xmax = 0)").label("inserted"))
        result = await self._session.execute(statement)
        return bool(result.scalar_one())

    async def get(self, job_id: int) -> Job | None:
        row = await self._session.scalar(
            select(JobRow).where(JobRow.id == job_id).execution_options(populate_existing=True)
        )
        return _to_job(row) if row is not None else None

    async def search(self, criteria: JobSearchCriteria) -> Page[Job]:
        where = and_(true(), *_conditions(criteria))
        total = await self._session.scalar(select(func.count()).select_from(JobRow).where(where))
        rows = await self._session.scalars(
            select(JobRow)
            .where(where)
            .order_by(JobRow.last_seen_at.desc(), JobRow.first_seen_at.desc(), JobRow.id.desc())
            .offset((criteria.page - 1) * criteria.size)
            .limit(criteria.size)
            .execution_options(populate_existing=True)
        )
        return Page(
            items=tuple(_to_job(row) for row in rows),
            total=total or 0,
            page=criteria.page,
            size=criteria.size,
        )
