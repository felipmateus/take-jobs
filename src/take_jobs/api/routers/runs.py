"""`GET /collection-runs` and `GET /collection-runs/{run_id}`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from take_jobs.api.dependencies import get_run_query_service
from take_jobs.api.errors import responses
from take_jobs.api.params import PageParam, SizeParam
from take_jobs.api.schemas import RunDetailOut, RunPageOut, RunSummaryOut
from take_jobs.application.services import CollectionRunQueryService

router = APIRouter(tags=["collection runs"])


@router.get(
    "/collection-runs",
    response_model=RunPageOut,
    summary="List collection runs, newest first",
    responses=responses(422, 503),
)
async def list_runs(
    service: Annotated[CollectionRunQueryService, Depends(get_run_query_service)],
    page: PageParam = 1,
    size: SizeParam = 20,
) -> RunPageOut:
    found = await service.list(page, size)
    return RunPageOut(
        items=[RunSummaryOut.model_validate(run) for run in found.items],
        total=found.total,
        page=found.page,
        size=found.size,
        pages=found.pages,
    )


@router.get(
    "/collection-runs/{run_id}",
    response_model=RunDetailOut,
    summary="Get one collection run with its results",
    responses=responses(404, 422, 503),
)
async def get_run(
    run_id: int,
    service: Annotated[CollectionRunQueryService, Depends(get_run_query_service)],
) -> RunDetailOut:
    return RunDetailOut.model_validate(await service.get(run_id))
