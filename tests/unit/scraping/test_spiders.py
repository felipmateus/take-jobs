"""UT-040 to UT-049: slugs, start requests, paging, stop rules, error paths and Scrapy settings."""

import dataclasses
from urllib.parse import quote

import pytest
from scrapy import Request
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import TCPTimedOutError
from twisted.python.failure import Failure

from take_jobs.config import Settings
from take_jobs.domain.models import ScrapedJob
from take_jobs.infrastructure.scraping.registry import SOURCES, with_base_url
from take_jobs.infrastructure.scraping.settings import build_scrapy_settings
from take_jobs.infrastructure.scraping.slug import slugify_term
from take_jobs.infrastructure.scraping.spiders.base import TermState, build_outcomes
from take_jobs.infrastructure.scraping.spiders.infojobs import FRAGMENT_PATH, InfojobsSpider
from take_jobs.infrastructure.scraping.spiders.vagas import VagasSpider

VAGAS = "https://www.vagas.com.br"
INFOJOBS = "https://www.infojobs.com.br"


def response_for(url: str, html: str, term: str) -> HtmlResponse:
    return HtmlResponse(
        url=url,
        body=html.encode("utf-8"),
        encoding="utf-8",
        request=Request(url, meta={"term": term}),
    )


def split(results):
    results = list(results)
    jobs = [item for item in results if isinstance(item, ScrapedJob)]
    requests = [item for item in results if isinstance(item, Request)]
    return jobs, requests


def fragment_url(term: str, page: int) -> str:
    """The Infojobs list-fragment request the site's own script makes for page `page` (>= 2)."""
    listing = f"{INFOJOBS}/vagas-de-emprego-{slugify_term(term)}.aspx?page={page}"
    return f"{INFOJOBS}{FRAGMENT_PATH}?url={quote(listing, safe='')}"


def vagas_spider(terms=("python",), max_pages=20, base_url=VAGAS) -> VagasSpider:
    return VagasSpider(terms=list(terms), max_pages=max_pages, base_url=base_url)


def infojobs_spider(terms=("python",), max_pages=20) -> InfojobsSpider:
    return InfojobsSpider(terms=list(terms), max_pages=max_pages, base_url=INFOJOBS)


@pytest.mark.parametrize(
    ("term", "slug"),
    [
        ("desenvolvedor python", "desenvolvedor-python"),
        ("desenvolvedor .net", "desenvolvedor-net"),
        ("engenheiro de software", "engenheiro-de-software"),
        ("  Programador  ", "programador"),
        ("Desenvolvedor Sênior", "desenvolvedor-senior"),
    ],
)
def test_ut040_slugify_term(term: str, slug: str) -> None:
    assert slugify_term(term) == slug


def test_ut041_start_requests_per_term_carry_the_term() -> None:
    terms = ["desenvolvedor python", "programador"]

    vagas_requests = list(vagas_spider(terms).start_requests())
    infojobs_requests = list(infojobs_spider(terms).start_requests())

    assert [r.url for r in vagas_requests] == [
        f"{VAGAS}/vagas-de-desenvolvedor-python",
        f"{VAGAS}/vagas-de-programador",
    ]
    assert [r.url for r in infojobs_requests] == [
        f"{INFOJOBS}/vagas-de-emprego-desenvolvedor-python.aspx?page=1",
        f"{INFOJOBS}/vagas-de-emprego-programador.aspx?page=1",
    ]
    for request in (*vagas_requests, *infojobs_requests):
        assert request.meta["term"] in terms
        assert request.errback is not None


async def test_start_yields_the_same_requests_as_start_requests() -> None:
    spider = infojobs_spider(["a", "b"])

    started = [request async for request in spider.start()]

    assert [r.url for r in started] == [r.url for r in spider.start_requests()]


def test_ut042_vagas_page_yields_jobs_and_one_xhr_follow_up(read_fixture) -> None:
    spider = vagas_spider(["python"])
    first = response_for(f"{VAGAS}/vagas-de-python", read_fixture("vagas_python_p1.html"), "python")

    jobs, requests = split(spider.parse(first))

    assert len(jobs) == 40
    assert len(requests) == 1
    follow_up = requests[0]
    assert follow_up.url == f"{VAGAS}/vagas-de-python?pagina=2&q=python"
    assert follow_up.headers["X-Requested-With"] == b"XMLHttpRequest"
    assert follow_up.meta["term"] == "python"
    assert follow_up.callback == spider.parse
    assert follow_up.errback == spider.on_error

    last = response_for(follow_up.url, read_fixture("vagas_python_p2_xhr.html"), "python")
    jobs, requests = split(spider.parse(last))
    assert len(jobs) > 0
    assert requests == []
    state = spider.states["python"]
    assert state.finished
    assert state.pages == 2
    assert state.error is None


def test_first_page_request_has_no_xhr_header() -> None:
    request = next(iter(vagas_spider().start_requests()))

    assert b"X-Requested-With" not in request.headers


def test_ut043_infojobs_walks_fragment_pages_until_one_brings_no_unseen_id(read_fixture) -> None:
    spider = infojobs_spider(["python"])
    html = read_fixture("infojobs_python_p1.html")
    url = f"{INFOJOBS}/vagas-de-emprego-python.aspx?page=1"

    jobs, requests = split(spider.parse(response_for(url, html, "python")))
    assert len(jobs) == 20
    assert [r.url for r in requests] == [fragment_url("python", 2)]
    assert requests[0].meta["term"] == "python"
    assert b"X-Requested-With" not in requests[0].headers

    # Review round 7, issue 001: page 2 brings unseen ids, so the walk asks for page 3.
    page2 = response_for(
        requests[0].url, read_fixture("infojobs_python_p2_fragment.json"), "python"
    )
    jobs, requests = split(spider.parse(page2))
    assert len(jobs) == 20
    assert [r.url for r in requests] == [fragment_url("python", 3)]

    page3 = response_for(
        requests[0].url, read_fixture("infojobs_python_p3_fragment.json"), "python"
    )
    jobs, requests = split(spider.parse(page3))
    assert len(jobs) == 20
    assert [r.url for r in requests] == [fragment_url("python", 4)]

    # Past the end of the list the endpoint answers `eof` with no cards: no unseen id, stop.
    end = response_for(requests[0].url, read_fixture("infojobs_fragment_eof.json"), "python")
    jobs, requests = split(spider.parse(end))
    assert jobs == []
    assert requests == []
    state = spider.states["python"]
    assert state.pages == 4
    assert state.finished
    assert state.error is None
    assert len(state.jobs) == 60


def test_ut043_infojobs_stops_when_a_page_repeats_earlier_ids(read_fixture) -> None:
    spider = infojobs_spider(["python"])
    html = read_fixture("infojobs_python_p1.html")
    url = f"{INFOJOBS}/vagas-de-emprego-python.aspx?page=1"
    split(spider.parse(response_for(url, html, "python")))

    # A server that answers the next page with page 1 again: every id was already seen.
    jobs, requests = split(spider.parse(response_for(fragment_url("python", 2), html, "python")))

    assert jobs == []
    assert requests == []
    state = spider.states["python"]
    assert state.pages == 2
    assert state.finished
    assert state.error is None
    assert len(state.jobs) == 20


def test_infojobs_fragment_of_an_unexpected_shape_fails_only_its_term() -> None:
    spider = infojobs_spider(["a", "b"])
    wrong = response_for(fragment_url("b", 2), '{"eof": false}', "b")

    with pytest.raises(ValueError, match="listFragmentHTML") as raised:
        list(spider.parse(wrong))
    spider.on_spider_error(Failure(raised.value), wrong, spider)  # what Scrapy does (rule 28)

    assert spider.states["b"].error == (
        "parse error: ValueError: fragment response has no listFragmentHTML"
    )
    assert spider.states["b"].finished
    assert spider.states["a"] == TermState("a")


def test_ut044_page_cap_stops_the_walk(read_fixture) -> None:
    html = read_fixture("infojobs_python_p1.html")
    url = f"{INFOJOBS}/vagas-de-emprego-python.aspx?page=1"

    capped = infojobs_spider(["python"], max_pages=1)
    _, requests = split(capped.parse(response_for(url, html, "python")))
    assert requests == []
    assert capped.states["python"].finished

    spider = infojobs_spider(["python"], max_pages=20)
    spider.states["python"].pages = 18  # page 19 is being parsed
    _, requests = split(spider.parse(response_for(url, html, "python")))
    assert [r.url for r in requests] == [fragment_url("python", 20)]

    spider = infojobs_spider(["python"], max_pages=20)
    spider.states["python"].pages = 19  # page 20 is being parsed
    _, requests = split(spider.parse(response_for(url, html, "python")))
    assert requests == []
    assert spider.states["python"].pages == 20
    assert spider.states["python"].finished


def test_zero_cards_on_the_first_page_is_a_success_with_no_jobs(read_fixture) -> None:
    spider = vagas_spider(["php"])
    page = response_for(f"{VAGAS}/vagas-de-php", read_fixture("empty_listing.html"), "php")

    jobs, requests = split(spider.parse(page))

    assert jobs == []
    assert requests == []
    (outcome,) = build_outcomes("vagas", spider.states.values(), "finished")
    assert outcome.error is None
    assert outcome.pages == 1
    assert outcome.jobs == ()


def failure_for(spider, term: str, value: BaseException) -> Failure:
    failure = Failure(value)
    failure.request = Request(spider.first_page_url(term), meta={"term": term})
    return failure


def test_ut045_http_error_fails_only_its_term() -> None:
    spider = infojobs_spider(["a", "b"])
    response = HtmlResponse(url=spider.first_page_url("a"), status=403, body=b"no")
    response.request = Request(response.url, meta={"term": "a"})

    spider.on_error(failure_for(spider, "a", HttpError(response)))

    assert spider.states["a"].error == "HTTP 403 Forbidden"
    assert spider.states["a"].finished
    assert spider.states["b"] == TermState("b")


def test_http_error_term_is_found_through_the_response_when_the_failure_has_no_request() -> None:
    spider = infojobs_spider(["a", "b"])
    response = HtmlResponse(url=spider.first_page_url("b"), status=503, body=b"no")
    response.request = Request(response.url, meta={"term": "b"})

    spider.on_error(Failure(HttpError(response)))

    assert spider.states["b"].error == "HTTP 503 Service Unavailable"
    assert spider.states["a"].error is None


def test_ut046_seen_ids_do_not_cross_terms(read_fixture) -> None:
    spider = infojobs_spider(["a", "b"])
    html = read_fixture("infojobs_python_p1.html")

    jobs_a, _ = split(spider.parse(response_for(spider.first_page_url("a"), html, "a")))
    jobs_b, requests_b = split(spider.parse(response_for(spider.first_page_url("b"), html, "b")))

    assert len(jobs_a) == 20
    assert len(jobs_b) == 20
    assert [r.meta["term"] for r in requests_b] == ["b"]


def test_ut047_robots_block_is_reported_as_such() -> None:
    spider = vagas_spider(["a"])

    spider.on_error(failure_for(spider, "a", IgnoreRequest("Forbidden by robots.txt")))

    assert spider.states["a"].error == "blocked by robots.txt"


def test_other_download_errors_use_the_exception_type_and_message() -> None:
    spider = vagas_spider(["a", "b"])

    spider.on_error(failure_for(spider, "a", TCPTimedOutError()))
    spider.on_error(failure_for(spider, "b", IgnoreRequest("something else")))

    assert spider.states["a"].error is not None
    assert spider.states["a"].error.startswith("TCPTimedOutError: ")
    assert spider.states["b"].error == "IgnoreRequest: something else"


def test_errback_after_earlier_pages_keeps_their_jobs(read_fixture) -> None:
    spider = vagas_spider(["python"])
    first = response_for(f"{VAGAS}/vagas-de-python", read_fixture("vagas_python_p1.html"), "python")
    split(spider.parse(first))

    spider.on_error(failure_for(spider, "python", TCPTimedOutError()))

    state = spider.states["python"]
    assert len(state.jobs) == 40
    assert state.pages == 1
    assert state.error is not None


class FakeSettings:
    scrape_max_pages = 20
    scrape_download_delay = 1.0
    scrape_user_agent = "take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)"
    scrape_run_timeout_minutes = 60
    log_level = "INFO"


def test_ut048_scrapy_settings_follow_the_contract() -> None:
    settings = build_scrapy_settings(Settings(_env_file=None))

    assert settings["ROBOTSTXT_OBEY"] is True
    assert settings["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert settings["DOWNLOAD_DELAY"] == 1.0
    assert settings["RANDOMIZE_DOWNLOAD_DELAY"] is False
    assert settings["DOWNLOAD_DELAY_JITTER"] == 0
    assert settings["AUTOTHROTTLE_ENABLED"] is False
    assert settings["TWISTED_REACTOR"] is None
    assert settings["DOWNLOAD_TIMEOUT"] == 30
    assert settings["CLOSESPIDER_TIMEOUT"] == 3000
    assert settings["USER_AGENT"] == "take-jobs/2.0 (+https://github.com/felipmateus/take-jobs)"
    assert settings["ITEM_PIPELINES"] == {}
    assert settings["LOG_LEVEL"] == "WARNING"


def test_scrapy_settings_follow_custom_values() -> None:
    class Custom(FakeSettings):
        scrape_download_delay = 2.5
        scrape_user_agent = "bot/1"
        scrape_run_timeout_minutes = 20
        log_level = "DEBUG"

    settings = build_scrapy_settings(Custom())

    assert settings["DOWNLOAD_DELAY"] == 2.5
    assert settings["USER_AGENT"] == "bot/1"
    assert settings["CLOSESPIDER_TIMEOUT"] == 600
    assert settings["LOG_LEVEL"] == "DEBUG"


def test_ut049_spider_error_fails_only_that_term_and_keeps_earlier_jobs(read_fixture) -> None:
    spider = vagas_spider(["A", "B"])
    first = response_for(f"{VAGAS}/vagas-de-a", read_fixture("vagas_python_p1.html"), "A")
    split(spider.parse(first))
    broken = response_for(f"{VAGAS}/vagas-de-a?pagina=2", "<html></html>", "A")

    spider.on_spider_error(Failure(AttributeError("x")), broken, spider)

    state_a = spider.states["A"]
    assert state_a.error == "parse error: AttributeError: x"
    assert state_a.finished
    assert len(state_a.jobs) == 40
    # Nothing more is requested for A, even if its page is parsed afterwards.
    assert split(spider.parse(broken)) == ([], [])
    assert spider.states["B"] == TermState("B")


def test_spider_error_for_a_response_without_a_known_term_is_ignored() -> None:
    spider = vagas_spider(["A"])
    stray = HtmlResponse(url=f"{VAGAS}/x", body=b"")  # no request attached

    spider.on_spider_error(Failure(ValueError("boom")), stray, spider)
    spider.on_spider_error(
        Failure(ValueError("boom")), response_for(f"{VAGAS}/x", "", "unknown"), spider
    )

    assert spider.states["A"].error is None


def test_ut039_off_origin_next_link_fails_the_term_and_issues_no_request() -> None:
    spider = vagas_spider(["python"], base_url="http://127.0.0.1:9999")
    html = (
        '<li class="vaga"><a class="link-detalhes-vaga" data-id-vaga="1" title="Dev"'
        ' href="/vagas/v1/dev"></a></li>'
        '<a id="maisVagas" data-url="https://www.vagas.com.br/vagas-de-python?pagina=2"></a>'
    )
    page = response_for("http://127.0.0.1:9999/vagas-de-python", html, "python")

    jobs, requests = split(spider.parse(page))

    assert spider.allowed_domains == ["127.0.0.1"]
    assert [job.external_id for job in jobs] == ["1"]
    assert requests == []
    state = spider.states["python"]
    assert state.error is not None
    assert state.error.startswith("parse error: OffOriginURLError:")
    assert "https://www.vagas.com.br/vagas-de-python?pagina=2" in state.error
    assert len(state.jobs) == 1  # the page's jobs are kept


def test_allowed_domains_come_from_the_base_url() -> None:
    assert vagas_spider().allowed_domains == ["www.vagas.com.br"]
    assert infojobs_spider().allowed_domains == ["www.infojobs.com.br"]


def test_registry_lists_both_sources_and_can_be_pointed_at_a_local_server() -> None:
    assert set(SOURCES) == {"vagas", "infojobs"}
    assert SOURCES["vagas"].spider is VagasSpider
    assert SOURCES["vagas"].base_url == VAGAS
    assert SOURCES["infojobs"].base_url == INFOJOBS

    local = with_base_url(SOURCES, "http://127.0.0.1:9999")

    assert {s.base_url for s in local.values()} == {"http://127.0.0.1:9999"}
    assert local["vagas"].spider is VagasSpider
    assert SOURCES["vagas"].base_url == VAGAS  # the real registry is untouched
    assert dataclasses.is_dataclass(local["vagas"])


def test_duplicate_terms_collapse_into_one_state() -> None:
    spider = vagas_spider(["a", "b", "a"])

    assert spider.terms == ["a", "b"]
    assert list(spider.states) == ["a", "b"]
