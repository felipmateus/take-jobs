"""One error shape for every HTTP failure: `{"error": {"code", "message", "details"}}`."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from take_jobs.api.schemas import ErrorOut
from take_jobs.application.errors import (
    CollectionRunNotFoundError,
    InvalidPeriodError,
    JobNotFoundError,
)

logger = logging.getLogger("take_jobs.api")

DATABASE_UNAVAILABLE = "The database is unavailable. Try again later."

# Documented for every route in OpenAPI (`responses=`); the status codes each route can answer.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "Resource not found."},
    422: {"model": ErrorOut, "description": "Invalid request parameters."},
    503: {"model": ErrorOut, "description": "The database is unavailable."},
}


def responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: ERROR_RESPONSES[code] for code in codes}


def error_response(
    status_code: int, code: str, message: str, details: list[dict[str, str]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


# Connection failures surface as these SQLAlchemy errors once a connection exists, and as the raw
# `OSError` family (refused, unreachable, timed out) while one is being opened.
DATABASE_ERRORS = (OperationalError, InterfaceError, PoolTimeoutError, OSError)


def _field(location: tuple[Any, ...]) -> str:
    """`("query", "source", 0)` -> `source`; `("path", "job_id")` -> `job_id`."""
    parts = [str(part) for part in location[1:] if not isinstance(part, int)]
    return ".".join(parts)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details: dict[str, str] = {}
    for error in exc.errors():
        details.setdefault(_field(tuple(error["loc"])), str(error["msg"]))
    return error_response(
        422,
        "validation_error",
        "Invalid request parameters.",
        jsonable_encoder(
            [{"field": field, "message": message} for field, message in details.items()]
        ),
    )


async def _invalid_period(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, InvalidPeriodError)
    return error_response(
        422,
        "invalid_period",
        f"seen_from ({exc.seen_from.isoformat()}) must be on or before "
        f"seen_to ({exc.seen_to.isoformat()}).",
    )


async def _job_not_found(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobNotFoundError)
    return error_response(404, "job_not_found", f"Job {exc.job_id} was not found.")


async def _run_not_found(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CollectionRunNotFoundError)
    return error_response(
        404, "collection_run_not_found", f"Collection run {exc.run_id} was not found."
    )


async def _database_unavailable(_: Request, exc: Exception) -> JSONResponse:
    logger.warning("event=api_database_unavailable error=%s: %s", type(exc).__name__, exc)
    return error_response(503, "database_unavailable", DATABASE_UNAVAILABLE)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        return error_response(404, "not_found", "The requested resource was not found.")
    if exc.status_code == 405:
        return error_response(405, "method_not_allowed", "Method not allowed.")
    return error_response(exc.status_code, "http_error", str(exc.detail))


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "event=api_unhandled_error method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return error_response(500, "internal_error", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(InvalidPeriodError, _invalid_period)
    app.add_exception_handler(JobNotFoundError, _job_not_found)
    app.add_exception_handler(CollectionRunNotFoundError, _run_not_found)
    for database_error in DATABASE_ERRORS:
        app.add_exception_handler(database_error, _database_unavailable)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
