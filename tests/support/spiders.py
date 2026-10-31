"""Spiders that misbehave on purpose, to prove error paths through a real Scrapy crawl."""

from take_jobs.infrastructure.scraping.parsers import vagas
from take_jobs.infrastructure.scraping.parsers.common import ListingPage
from take_jobs.infrastructure.scraping.spiders.vagas import VagasSpider


def parse_then_fail_on_page_two(html: str, page_url: str) -> ListingPage:
    if "pagina=2" in page_url:
        raise ValueError("boom")
    return vagas.parse_listing(html, page_url)


class FailingSecondPageVagasSpider(VagasSpider):
    """Parses page 1 normally and raises inside the callback of page 2 (rule 28)."""

    parse_page = staticmethod(parse_then_fail_on_page_two)
