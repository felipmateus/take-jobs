"""Shared spider logic: per-term state, stop rules and the two mandatory error paths.

One spider walks every term of one source (ADR-003). State is kept per term, so an error or a
finished term never leaks into another (rules 17 and 28; ADR-002).
"""

from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, ClassVar, Self
from urllib.parse import urlsplit

import scrapy
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Response
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.python.failure import Failure

from take_jobs.domain.models import CombinationOutcome, ScrapedJob
from take_jobs.infrastructure.scraping.parsers.common import ListingPage


class OffOriginURLError(Exception):
    """A URL taken from a page points outside the spider's `base_url` origin."""


@dataclass(slots=True)
class TermState:
    """Collection state of one source x term combination."""

    term: str
    seen: set[str] = field(default_factory=set)
    jobs: list[ScrapedJob] = field(default_factory=list)
    pages: int = 0
    finished: bool = False
    error: str | None = None


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def describe_failure(failure: Failure) -> str:
    """Request errback message (`_spec.md` > Integration Points)."""
    value = failure.value
    if isinstance(value, HttpError):
        status = value.response.status
        try:
            reason = HTTPStatus(status).phrase
        except ValueError:
            reason = ""
        return f"HTTP {status} {reason}".strip()
    if isinstance(value, IgnoreRequest) and "robots.txt" in str(value):
        return "blocked by robots.txt"
    return f"{type(value).__name__}: {value}"


def _failed_term(failure: Failure) -> str | None:
    """The term a failed request belonged to (Scrapy sets `failure.request`; HTTP errors also
    carry the response, which points back to its request)."""
    request = getattr(failure, "request", None)
    if request is None:
        request = getattr(getattr(failure.value, "response", None), "request", None)
    return request.meta.get("term") if request is not None else None


class ListingSpider(scrapy.Spider):
    """Base for a source's spider. Subclasses set the class variables and `build_page_url`."""

    # Set by subclasses.
    parse_page: ClassVar[Callable[[str, str], ListingPage]]
    follow_headers: ClassVar[dict[str, str]] = {}

    def __init__(self, terms: Sequence[str], max_pages: int, base_url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.terms = list(dict.fromkeys(terms))
        self.max_pages = max_pages
        self.base_url = base_url.rstrip("/")
        self.allowed_domains = [urlsplit(self.base_url).hostname or ""]
        self.states: dict[str, TermState] = {term: TermState(term) for term in self.terms}
        self.close_reason: str | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any) -> Self:
        spider = super().from_crawler(crawler, *args, **kwargs)
        # An exception raised inside a callback never reaches the errback; this signal does
        # (rule 28, ADR-002). Both paths are mandatory.
        crawler.signals.connect(spider.on_spider_error, signal=signals.spider_error)
        return spider

    # -- requests ---------------------------------------------------------------------------

    def first_page_url(self, term: str) -> str:
        raise NotImplementedError

    def next_page_url(self, term: str, listing: ListingPage, response: Response) -> str | None:
        raise NotImplementedError

    def make_request(self, url: str, term: str, *, follow_up: bool) -> scrapy.Request:
        return scrapy.Request(
            url,
            callback=self.parse,
            errback=self.on_error,
            headers=self.follow_headers if follow_up else None,
            meta={"term": term},
        )

    def start_requests(self) -> Iterator[scrapy.Request]:
        for term in self.terms:
            yield self.make_request(self.first_page_url(term), term, follow_up=False)

    async def start(self) -> AsyncIterator[scrapy.Request]:
        for request in self.start_requests():
            yield request

    # -- callbacks --------------------------------------------------------------------------

    def parse(self, response: Response, **kwargs: Any) -> Iterable[ScrapedJob | scrapy.Request]:
        term = response.meta["term"]
        state = self.states[term]
        if state.finished:
            return
        listing = self.parse_page(response.text, response.url)
        state.pages += 1
        fresh = [job for job in listing.jobs if job.external_id not in state.seen]
        for job in fresh:
            state.seen.add(job.external_id)
            state.jobs.append(job)
            yield job
        # Rule 17: stop on a page without an unseen job, at the page cap, or without a next page.
        if not fresh or state.pages >= self.max_pages:
            state.finished = True
            return
        next_url = self.next_page_url(term, listing, response)
        if next_url is None:
            state.finished = True
            return
        if _origin(next_url) != _origin(self.base_url):
            self.record_parse_error(state, OffOriginURLError(next_url))
            return
        yield self.make_request(next_url, term, follow_up=True)

    def on_error(self, failure: Failure) -> None:
        """Request errback: HTTP errors, robots.txt blocks, timeouts and other download errors."""
        state = self.states.get(_failed_term(failure))
        if state is None or state.finished:
            return
        state.error = describe_failure(failure)
        state.finished = True

    def on_spider_error(self, failure: Failure, response: Response, spider: scrapy.Spider) -> None:
        """`spider_error` handler: an exception raised while handling `response` (rule 28)."""
        if spider is not self:
            return
        try:
            term = response.meta.get("term")
        except AttributeError:
            return
        state = self.states.get(term)
        if state is None:
            return
        self.record_parse_error(state, failure.value)

    def record_parse_error(self, state: TermState, error: BaseException) -> None:
        if state.error is None:
            state.error = f"parse error: {type(error).__name__}: {error}"
        state.finished = True

    def closed(self, reason: str) -> None:
        self.close_reason = reason


def build_outcomes(
    source: str, states: Iterable[TermState], close_reason: str | None
) -> tuple[CombinationOutcome, ...]:
    """Turn the per-term state into one outcome per term, given why the spider closed.

    `finished` keeps the recorded outcomes, except that a term that never finished (Scrapy dropped
    its request without calling the errback, for example the duplicate filter on a repeated URL)
    fails with `crawl closed: finished before the term completed`. `closespider_timeout` fails
    every unfinished term with `run time limit reached` (rule 25). Any other reason, including
    `None` and `shutdown`, fails them with `crawl closed: <reason>`, so a stopped crawl is never
    read as success.
    """
    if close_reason == "finished":
        unfinished_error = "crawl closed: finished before the term completed"
    elif close_reason == "closespider_timeout":
        unfinished_error = "run time limit reached"
    else:
        unfinished_error = f"crawl closed: {close_reason}"
    outcomes = []
    for state in states:
        error = state.error
        if error is None and not state.finished:
            error = unfinished_error
        outcomes.append(
            CombinationOutcome(
                source=source,
                term=state.term,
                jobs=tuple(state.jobs),
                pages=state.pages,
                error=error,
            )
        )
    return tuple(outcomes)
