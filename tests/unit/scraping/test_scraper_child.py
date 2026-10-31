"""UT-106 to UT-109, UT-116 and UT-119: the spawned crawl child, its hand-off and the network guard.

The process-level cases replace the child target with a top-level function from
`tests.support.child_targets` (the child must be able to import it). The `real crawl` cases run
the actual Scrapy crawl against the local fixture server.
"""

import functools
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from urllib.parse import quote

import pytest

from take_jobs.config import Settings
from take_jobs.domain.errors import ScrapeCrashedError, ScrapeInterruptedError
from take_jobs.domain.models import ScrapeReport
from take_jobs.infrastructure.scraping import scraper as scraper_module
from take_jobs.infrastructure.scraping.registry import SOURCES, SourceDefinition, with_base_url
from take_jobs.infrastructure.scraping.scraper import ScrapyJobScraper
from take_jobs.infrastructure.scraping.spiders.base import TermState, build_outcomes
from take_jobs.infrastructure.scraping.spiders.infojobs import FRAGMENT_PATH
from tests.support import child_targets
from tests.support.fixture_server import FixtureServer, Route, fragment_target, python_routes
from tests.support.socket_guard import install_test_socket_guard
from tests.support.spiders import FailingSecondPageVagasSpider


def make_scraper(sources=SOURCES, **kwargs) -> ScrapyJobScraper:
    return ScrapyJobScraper(sources, Settings(_env_file=None), **kwargs)


def run_in_thread(target: Callable[[], object]) -> tuple[threading.Thread, dict[str, object]]:
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["result"] = target()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread, box


@pytest.fixture
def child_exit(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bool, int | None]]:
    """Records (alive, exitcode) of the crawl child right before the scraper reaps it."""
    seen: list[tuple[bool, int | None]] = []
    original = ScrapyJobScraper._reap

    def spy(process) -> None:
        if process.pid is not None:
            seen.append((process.is_alive(), process.exitcode))
        original(process)

    monkeypatch.setattr(ScrapyJobScraper, "_reap", staticmethod(spy))
    return seen


def started_state(term: str, *, finished: bool, error: str | None = None) -> TermState:
    state = TermState(term, finished=finished, error=error, pages=2)
    return state


def test_ut106_closespider_timeout_fails_unfinished_terms_only() -> None:
    done = started_state("A", finished=True)
    pending = started_state("B", finished=False)

    outcome_a, outcome_b = build_outcomes("vagas", [done, pending], "closespider_timeout")

    assert outcome_a.error is None
    assert outcome_b.error == "run time limit reached"
    assert outcome_b.pages == 2  # what was collected so far is kept


def test_ut119_finished_reason_fails_a_term_that_never_finished() -> None:
    """UT-119 (review round 7, issue 002): Scrapy dropped a request without the errback."""
    never_ran = TermState("A")
    walked = started_state("B", finished=False)

    outcome_a, outcome_b = build_outcomes("vagas", [never_ran, walked], "finished")

    for outcome in (outcome_a, outcome_b):
        assert outcome.error == "crawl closed: finished before the term completed"
    assert outcome_a.pages == 0
    assert outcome_b.pages == 2  # what was collected so far is kept


def test_ut119_finished_reason_keeps_the_recorded_outcomes() -> None:
    """UT-119: a term that recorded its outcome keeps it under the `finished` reason."""
    failed = started_state("A", finished=True, error="HTTP 403 Forbidden")
    ok = started_state("B", finished=True)

    outcome_a, outcome_b = build_outcomes("infojobs", [failed, ok], "finished")

    assert (outcome_a.error, outcome_b.error) == ("HTTP 403 Forbidden", None)
    assert outcome_a.source == "infojobs"


@pytest.mark.parametrize("reason", [None, "shutdown", "cancelled"])
def test_ut107_any_other_close_reason_is_never_success(reason: str | None) -> None:
    (outcome,) = build_outcomes("vagas", [started_state("A", finished=False)], reason)

    assert outcome.error == f"crawl closed: {reason}"


def test_ut107_recorded_error_wins_over_the_close_reason() -> None:
    (outcome,) = build_outcomes(
        "vagas",
        [started_state("A", finished=True, error="parse error: X: y")],
        "closespider_timeout",
    )

    assert outcome.error == "parse error: X: y"


def test_ut107_interrupt_during_the_crawl_kills_the_child(
    monkeypatch: pytest.MonkeyPatch, child_exit
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.sleep_then_report)
    scraper = make_scraper()
    thread, box = run_in_thread(lambda: scraper.scrape(["python"]))

    time.sleep(1)
    started = time.monotonic()
    scraper.interrupt()
    thread.join(7)

    assert not thread.is_alive()
    assert time.monotonic() - started < 7
    assert isinstance(box.get("error"), ScrapeInterruptedError)
    assert child_exit == [(False, -15)]  # SIGTERM; no SIGKILL needed


def test_ut107_interrupt_before_scrape_never_starts_a_crawl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.sleep_then_report)
    scraper = make_scraper()

    scraper.interrupt()
    started = time.monotonic()
    with pytest.raises(ScrapeInterruptedError):
        scraper.scrape(["python"])

    assert time.monotonic() - started < 7
    assert multiprocessing.active_children() == []


def test_ut107_interrupt_landing_during_start_stops_the_child_right_after(
    monkeypatch: pytest.MonkeyPatch, child_exit
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.sleep_then_report)
    scraper = make_scraper()
    original_start = multiprocessing.context.SpawnProcess.start

    def start_then_interrupt(process) -> None:
        original_start(process)
        scraper.interrupt()  # `scrape()` has not yet recorded the child: only the flag is set

    monkeypatch.setattr(multiprocessing.context.SpawnProcess, "start", start_then_interrupt)

    started = time.monotonic()
    with pytest.raises(ScrapeInterruptedError):
        scraper.scrape(["python"])

    assert time.monotonic() - started < 7
    assert child_exit == [(False, -15)]


def test_ut107_interrupt_from_a_signal_handler_in_the_scraping_thread(
    monkeypatch: pytest.MonkeyPatch, child_exit
) -> None:
    """The CLI calls `interrupt()` from its signal handler while `scrape()` blocks in the same
    (main) thread."""
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.sleep_then_report)
    scraper = make_scraper()
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: scraper.interrupt())
    timer = threading.Timer(1, os.kill, (os.getpid(), signal.SIGTERM))
    try:
        timer.start()
        started = time.monotonic()
        with pytest.raises(ScrapeInterruptedError):
            scraper.scrape(["python"])
    finally:
        timer.cancel()
        signal.signal(signal.SIGTERM, previous)

    assert time.monotonic() - started < 8
    assert child_exit == [(False, -15)]


def test_ut107_an_interrupted_crawl_is_interrupted_whatever_the_child_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.send_large_report)
    scraper = make_scraper()
    scraper.interrupt()

    with pytest.raises(ScrapeInterruptedError):
        scraper.scrape(["python"])


def test_ut108_child_exiting_without_a_report_is_a_crash_not_a_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.crash_without_report)
    scraper = make_scraper()

    thread, box = run_in_thread(lambda: scraper.scrape(["python"]))
    thread.join(10)

    assert not thread.is_alive(), "scrape() hung after the child died"
    error = box.get("error")
    assert isinstance(error, ScrapeCrashedError)
    assert "code 1" in str(error)


def test_ut109_report_larger_than_the_pipe_buffer_crosses_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scraper_module, "_CHILD_TARGET", child_targets.send_large_report)
    scraper = make_scraper()

    thread, box = run_in_thread(lambda: scraper.scrape(["python"]))
    thread.join(30)

    assert not thread.is_alive(), "scrape() deadlocked on a large report"
    report = box.get("result")
    assert isinstance(report, ScrapeReport)
    expected = child_targets.large_report()
    assert len(report.outcomes[0].jobs) == 15_000
    assert report == expected


def test_socket_guard_blocks_connect_and_connect_ex_in_a_spawned_child() -> None:
    context = multiprocessing.get_context("spawn")

    def probe(allow_hosts: list[str] | None) -> dict[str, str]:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=child_targets.probe_socket_guard, args=(sender, allow_hosts), daemon=True
        )
        process.start()
        sender.close()
        result = receiver.recv()
        process.join(10)
        return result

    default = probe(None)
    only_ipv6 = probe(["::1"])

    assert default == {
        "connect:remote": "blocked",
        "connect:loopback": "refused",  # allowed through; nothing listens on port 9
        "connect_ex:remote": "blocked",
        "connect_ex:loopback": "returned " + default["connect_ex:loopback"].split()[-1],
    }
    assert default["connect_ex:loopback"] != "returned 0"
    assert only_ipv6["connect:loopback"] == "blocked"
    assert only_ipv6["connect_ex:loopback"] == "blocked"
    assert only_ipv6["connect_ex:remote"] == "blocked"


# -- real crawls against the local fixture server ----------------------------------------------


def crawl(server: FixtureServer, terms=("python",), **kwargs) -> ScrapeReport:
    scraper = make_scraper(
        with_base_url(SOURCES, server.url), child_initializer=install_test_socket_guard, **kwargs
    )
    return scraper.scrape(list(terms))


def test_real_crawl_collects_both_sources_and_can_run_twice_in_one_process() -> None:
    with FixtureServer(python_routes()) as server:
        first = crawl(server)
        second = crawl(server)  # a Twisted reactor cannot restart; the child makes this possible

    for report in (first, second):
        by_source = {outcome.source: outcome for outcome in report.outcomes}
        assert set(by_source) == {"vagas", "infojobs"}
        assert by_source["vagas"].pages == 2
        assert len(by_source["vagas"].jobs) == 43
        # Pages 1-3 bring 20 unseen jobs each; page 4 is the end of the list (no unseen id).
        assert by_source["infojobs"].pages == 4
        assert len(by_source["infojobs"].jobs) == 60
        assert all(outcome.error is None for outcome in report.outcomes)
        assert all(outcome.term == "python" for outcome in report.outcomes)
    assert first == second


def test_real_crawl_follow_up_page_is_requested_as_xhr_with_a_referer() -> None:
    with FixtureServer(python_routes()) as server:
        crawl(server)
        follow_up = next(h for h in server.hits if "pagina=2" in h.target)

    assert follow_up.headers["X-Requested-With"] == "XMLHttpRequest"
    assert follow_up.headers["Referer"].endswith("/vagas-de-python")
    assert follow_up.headers["User-Agent"].startswith("take-jobs/2.0")


def test_real_crawl_infojobs_follow_ups_use_the_fragment_endpoint() -> None:
    """Review round 7, issue 001: `?page=N` HTML returns page 1 on the real site for every N."""
    with FixtureServer(python_routes()) as server:
        crawl(server)
        infojobs_hits = [
            h.target
            for h in server.listing_hits()
            if h.target.startswith(("/vagas-de-emprego", FRAGMENT_PATH))
        ]
        origin = quote(f"{server.url}/vagas-de-emprego-python.aspx?page=", safe="")

    assert infojobs_hits[0] == "/vagas-de-emprego-python.aspx?page=1"
    assert infojobs_hits[1:] == [f"{FRAGMENT_PATH}?url={origin}{page}" for page in (2, 3, 4)]


def test_ut119_real_crawl_redirect_to_an_already_fetched_url_fails_the_term() -> None:
    """UT-119 (review round 7, issue 002): the duplicate filter drops it without the errback."""
    routes = python_routes()
    routes[fragment_target("/vagas-de-emprego-python.aspx?page=2")] = Route(
        status=302, location="/vagas-de-emprego-python.aspx?page=1"
    )
    with FixtureServer(routes) as server:
        report = crawl(server)

    by_source = {outcome.source: outcome for outcome in report.outcomes}
    assert by_source["infojobs"].pages == 1
    assert len(by_source["infojobs"].jobs) == 20  # page 1 is kept
    assert by_source["infojobs"].error == "crawl closed: finished before the term completed"
    assert by_source["vagas"].error is None


def test_ut119_real_crawl_terms_with_one_slug_never_read_as_success() -> None:
    """UT-119 (review round 7, issue 002): `Settings` rejects these; a caller sees this."""
    with FixtureServer(python_routes()) as server:
        report = crawl(server, terms=("python", "Python"))

    for source in ("vagas", "infojobs"):
        first, second = (o for o in report.outcomes if o.source == source)
        assert (first.term, first.error) == ("python", None)
        assert first.pages > 0
        assert (second.term, second.pages) == ("Python", 0)
        assert second.error == "crawl closed: finished before the term completed"


def test_real_crawl_http_error_fails_only_that_source() -> None:
    routes = python_routes()
    routes["/vagas-de-emprego-python.aspx?page=1"] = Route(status=403, body=b"forbidden")
    with FixtureServer(routes) as server:
        report = crawl(server)

    by_source = {outcome.source: outcome for outcome in report.outcomes}
    assert by_source["infojobs"].error == "HTTP 403 Forbidden"
    assert by_source["infojobs"].jobs == ()
    assert by_source["vagas"].error is None


def test_real_crawl_obeys_robots_txt() -> None:
    with FixtureServer(python_routes(), robots_txt=b"User-agent: *\nDisallow: /\n") as server:
        report = crawl(server)
        listing_hits = server.listing_hits()

    assert [outcome.error for outcome in report.outcomes] == ["blocked by robots.txt"] * 2
    assert listing_hits == []


def test_real_crawl_exception_in_a_callback_reaches_the_spider_error_handler() -> None:
    with FixtureServer(python_routes()) as server:
        sources = {
            "vagas": SourceDefinition("vagas", FailingSecondPageVagasSpider, server.url),
        }
        scraper = make_scraper(sources, child_initializer=install_test_socket_guard)
        report = scraper.scrape(["python"])

    (outcome,) = report.outcomes
    assert outcome.error == "parse error: ValueError: boom"
    assert len(outcome.jobs) == 40  # page 1 is kept
    assert outcome.pages == 1


def test_real_crawl_interrupt_stops_a_crawl_blocked_on_slow_responses(child_exit) -> None:
    with FixtureServer(python_routes(delay_s=25)) as server:
        scraper = make_scraper(
            with_base_url(SOURCES, server.url), child_initializer=install_test_socket_guard
        )
        thread, box = run_in_thread(lambda: scraper.scrape(["python"]))
        assert server.first_listing_hit.wait(20)

        started = time.monotonic()
        scraper.interrupt()
        thread.join(7)

    assert not thread.is_alive()
    assert time.monotonic() - started < 5
    assert isinstance(box.get("error"), ScrapeInterruptedError)
    assert child_exit == [(False, -15)]  # the real child dies on SIGTERM: no Scrapy handler


def test_ut116_guard_in_the_child_blocks_a_real_scrapy_request() -> None:
    with FixtureServer(python_routes()) as server:
        blocked = functools.partial(install_test_socket_guard, allow_hosts=["::1"])
        report = make_scraper(with_base_url(SOURCES, server.url), child_initializer=blocked).scrape(
            ["python"]
        )
        blocked_hits = server.hit_count()

        # Control: the default guard allows loopback, so the same scrape reaches the server.
        control = crawl(server)
        control_hits = server.hit_count() - blocked_hits

    assert len(report.outcomes) == 2
    for outcome in report.outcomes:
        assert outcome.error is not None
        assert outcome.error.startswith("SocketConnectBlockedError: ")
    assert blocked_hits == 0
    assert all(outcome.error is None for outcome in control.outcomes)
    assert control_hits >= 1
