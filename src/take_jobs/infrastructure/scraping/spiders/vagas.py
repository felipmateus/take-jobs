"""vagas.com spider: `/vagas-de-{slug}`, next pages from `a#maisVagas@data-url` via XHR."""

from typing import ClassVar

from scrapy.http import Response

from take_jobs.infrastructure.scraping.parsers import vagas
from take_jobs.infrastructure.scraping.parsers.common import ListingPage
from take_jobs.infrastructure.scraping.slug import slugify_term
from take_jobs.infrastructure.scraping.spiders.base import ListingSpider


class VagasSpider(ListingSpider):
    name = "vagas"
    parse_page = staticmethod(vagas.parse_listing)
    # Without this header the site answers 403 to the follow-up pages. Scrapy adds `Referer`.
    follow_headers: ClassVar[dict[str, str]] = {"X-Requested-With": "XMLHttpRequest"}

    def first_page_url(self, term: str) -> str:
        return f"{self.base_url}/vagas-de-{slugify_term(term)}"

    def next_page_url(self, term: str, listing: ListingPage, response: Response) -> str | None:
        return listing.next_url
