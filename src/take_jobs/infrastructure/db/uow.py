"""SQLAlchemy `UnitOfWork`: one session shared by the repositories and the probe."""

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from take_jobs.infrastructure.db.job_repository import SqlAlchemyJobRepository
from take_jobs.infrastructure.db.probe import SqlAlchemyJobStoreProbe
from take_jobs.infrastructure.db.run_repository import SqlAlchemyCollectionRunRepository


class SqlAlchemyUnitOfWork:
    jobs: SqlAlchemyJobRepository
    runs: SqlAlchemyCollectionRunRepository
    probe: SqlAlchemyJobStoreProbe

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        session = self._sessionmaker()
        self._session = session
        self.jobs = SqlAlchemyJobRepository(session)
        self.runs = SqlAlchemyCollectionRunRepository(session)
        self.probe = SqlAlchemyJobStoreProbe(session)
        return self

    async def __aexit__(self, *exc: object) -> None:
        session = self._session
        if session is None:
            return
        self._session = None
        try:
            if all(item is None for item in exc):
                await session.commit()
            else:
                await session.rollback()
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()
