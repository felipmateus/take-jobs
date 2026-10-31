"""PostgreSQL implementation of `JobStoreProbe`."""

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from take_jobs.infrastructure.db.models import JobRow


class SqlAlchemyJobStoreProbe:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_empty(self) -> bool:
        return not await self._session.scalar(select(exists().select_from(JobRow)))

    async def ping(self) -> None:
        await self._session.execute(text("SELECT 1"))
