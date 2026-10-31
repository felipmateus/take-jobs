"""Pagination parameters shared by the list routes (`_dx.md`: `page` >= 1, `size` 1-100)."""

from typing import Annotated

from fastapi import Query

# The documented rule is `page >= 1`. The ceiling only keeps `(page - 1) * size` inside PostgreSQL's
# bigint, so an absurd page is a `validation_error` instead of an unhandled database error.
MAX_PAGE = 1_000_000_000

PageParam = Annotated[int, Query(ge=1, le=MAX_PAGE)]
SizeParam = Annotated[int, Query(ge=1, le=100)]
