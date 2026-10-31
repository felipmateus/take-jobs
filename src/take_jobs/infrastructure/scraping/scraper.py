"""`ScrapyJobScraper`: runs the crawl in a spawned child process (ADR-002, Safety Invariant 5).

The Twisted reactor cannot restart, so each `scrape()` call starts a fresh `spawn` child that runs
one `CrawlerProcess` and sends the `ScrapeReport` back through a one-way pipe. The parent never
starts a reactor, reads the report **before** joining the child (a report larger than the pipe
buffer would otherwise deadlock), and alone decides about interruption (rule 24).
"""

import multiprocessing
import signal
import threading
import warnings
from collections.abc import Callable, Mapping, Sequence
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any

from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import ScrapyDeprecationWarning

from take_jobs.domain.errors import ScrapeCrashedError, ScrapeInterruptedError
from take_jobs.domain.models import CombinationOutcome, ScrapeReport
from take_jobs.infrastructure.scraping.registry import SourceDefinition
from take_jobs.infrastructure.scraping.settings import ScrapeSettings, build_scrapy_settings
from take_jobs.infrastructure.scraping.spiders.base import ListingSpider, build_outcomes

# How long `interrupt()` waits for the child to die after SIGTERM before it sends SIGKILL.
TERMINATE_GRACE_S = 5.0
# How long the parent waits for a child that already sent its report to exit.
EXIT_GRACE_S = 10.0


def run_crawl(
    sources: Mapping[str, SourceDefinition],
    scrapy_settings: Mapping[str, Any],
    terms: Sequence[str],
    max_pages: int,
) -> ScrapeReport:
    """Crawl every source x term in this process and return the report. Child process only."""
    # RANDOMIZE_DOWNLOAD_DELAY=False is part of the settings contract (UT-048) and is still
    # honored by Scrapy; DOWNLOAD_DELAY_JITTER=0 says the same without the deprecation notice.
    warnings.filterwarnings(
        "ignore",
        message="The RANDOMIZE_DOWNLOAD_DELAY setting is deprecated",
        category=ScrapyDeprecationWarning,
    )
    process = CrawlerProcess(settings=dict(scrapy_settings))
    crawlers = []
    for source in sources.values():
        crawler = process.create_crawler(source.spider)
        process.crawl(crawler, terms=list(terms), max_pages=max_pages, base_url=source.base_url)
        crawlers.append((source, crawler))
    # Scrapy installs no signal handlers: the collector is the only signal handler (rule 24).
    process.start(install_signal_handlers=False)

    outcomes: list[CombinationOutcome] = []
    for source, crawler in crawlers:
        spider = crawler.spider
        if not isinstance(spider, ListingSpider):
            raise RuntimeError(f"the {source.id} spider did not start")
        outcomes.extend(build_outcomes(source.id, spider.states.values(), spider.close_reason))
    return ScrapeReport(outcomes=tuple(outcomes))


def crawl_child(
    connection: Connection,
    sources: Mapping[str, SourceDefinition],
    scrapy_settings: Mapping[str, Any],
    terms: Sequence[str],
    max_pages: int,
    child_initializer: Callable[[], None] | None,
) -> None:
    """Entry point of the spawned child."""
    # A terminal Ctrl+C reaches the whole process group; only the collector reacts to it.
    # SIGTERM keeps its default action, so `interrupt()` ends this process at once.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        if child_initializer is not None:
            child_initializer()
        connection.send(run_crawl(sources, scrapy_settings, terms, max_pages))
    finally:
        connection.close()


# Looked up on every `scrape()` call. Tests replace it with a top-level function of the same
# signature, which spawn can import in the child.
_CHILD_TARGET: Callable[..., None] = crawl_child


class ScrapyJobScraper:
    """Implements the `JobScraper` port."""

    def __init__(
        self,
        sources: Mapping[str, SourceDefinition],
        settings: ScrapeSettings,
        *,
        child_initializer: Callable[[], None] | None = None,
    ) -> None:
        # A plain dict: it is pickled across the spawn boundary.
        self._sources = dict(sources)
        self._settings = settings
        self._child_initializer = child_initializer
        self._interrupt_requested = threading.Event()
        self._lock = threading.RLock()  # re-entrant: `interrupt()` may run inside a signal handler
        self._process: BaseProcess | None = None

    def scrape(self, terms: Sequence[str]) -> ScrapeReport:
        if self._interrupt_requested.is_set():
            raise ScrapeInterruptedError("interrupted before the crawl started")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_CHILD_TARGET,
            args=(
                sender,
                self._sources,
                build_scrapy_settings(self._settings),
                list(terms),
                self._settings.scrape_max_pages,
                self._child_initializer,
            ),
            daemon=True,
        )
        try:
            with self._lock:
                if self._interrupt_requested.is_set():
                    raise ScrapeInterruptedError("interrupted before the crawl started")
                process.start()
                self._process = process
            # Without this, EOF never reaches the parent when the child dies without a report.
            sender.close()
            if self._interrupt_requested.is_set():  # a request that landed during start()
                self._terminate(process)
                process.join()
                raise ScrapeInterruptedError("interrupted while the crawl was starting")
            return self._collect(process, receiver)
        finally:
            sender.close()
            receiver.close()
            with self._lock:
                self._process = None
            self._reap(process)

    def interrupt(self) -> None:
        self._interrupt_requested.set()
        with self._lock:
            process = self._process
        if process is not None:
            self._terminate(process)

    # -- internals --------------------------------------------------------------------------

    def _collect(self, process: BaseProcess, receiver: Connection) -> ScrapeReport:
        # Read before join: a report bigger than the pipe buffer blocks the child's send until
        # the parent reads, so joining first would deadlock.
        ready = wait([receiver, process.sentinel])
        report: object = None
        problem: str | None = None
        if receiver in ready or receiver.poll():
            try:
                report = receiver.recv()
            except EOFError:
                report = None
            except Exception as exc:
                problem = f"unreadable report: {type(exc).__name__}: {exc}"
        if self._interrupt_requested.is_set():
            # Whatever the child sent, a stopped crawl is never a result (rule 24).
            self._terminate(process)
            process.join()
            raise ScrapeInterruptedError("interrupted by signal")
        process.join(EXIT_GRACE_S)
        if process.is_alive():
            self._terminate(process)
            process.join()
        if report is None:
            detail = problem or "no report"
            raise ScrapeCrashedError(
                f"crawl process exited with code {process.exitcode} ({detail})"
            )
        if not isinstance(report, ScrapeReport):
            raise ScrapeCrashedError(f"crawl process sent {type(report).__name__}, not a report")
        if process.exitcode != 0:
            raise ScrapeCrashedError(
                f"crawl process exited with code {process.exitcode} after sending its report"
            )
        return report

    @staticmethod
    def _terminate(process: BaseProcess) -> None:
        """SIGTERM, wait up to `TERMINATE_GRACE_S`, then SIGKILL. Does not reap the child."""
        try:
            process.terminate()
            if not wait([process.sentinel], timeout=TERMINATE_GRACE_S):
                process.kill()
        except (ValueError, OSError):  # already reaped and closed
            return

    @staticmethod
    def _reap(process: BaseProcess) -> None:
        if process.pid is None:  # `start()` never ran
            return
        if process.is_alive():
            process.kill()
        process.join()
        process.close()
