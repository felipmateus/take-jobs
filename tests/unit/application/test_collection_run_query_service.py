"""UT-065: CollectionRunQueryService over in-memory fakes."""

from datetime import timedelta

import pytest

from take_jobs.application.errors import CollectionRunNotFoundError
from take_jobs.application.services import CollectionRunQueryService
from take_jobs.domain.models import RunStatus
from tests.fakes import NOW, InMemoryCollectionRunRepository, InMemoryStore


async def test_ut065_unknown_run_raises_not_found() -> None:
    service = CollectionRunQueryService(InMemoryCollectionRunRepository(InMemoryStore()))

    with pytest.raises(CollectionRunNotFoundError) as raised:
        await service.get(404)

    assert raised.value.run_id == 404


async def test_get_returns_the_run() -> None:
    store = InMemoryStore()
    run = store.add_run(started_at=NOW, status=RunStatus.SUCCESS)
    service = CollectionRunQueryService(InMemoryCollectionRunRepository(store))

    assert await service.get(run.id) == run


async def test_list_delegates_pagination_newest_first() -> None:
    store = InMemoryStore()
    for hours in (3, 2, 1):
        store.add_run(started_at=NOW - timedelta(hours=hours), status=RunStatus.SUCCESS)
    service = CollectionRunQueryService(InMemoryCollectionRunRepository(store))

    page = await service.list(page=2, size=2)

    assert (page.total, page.page, page.size) == (3, 2, 2)
    assert [run.id for run in page.items] == [1]
