"""Infojobs spider: page 1 is `/vagas-de-emprego-{slug}.aspx?page=1`, later pages are fragments.

The listing page loads further results by infinite scroll: the site's own script requests
`/mf-publicarea/VacancyList/GetVacancyListFragment?url=<listing URL with ?page=N>` and appends the
`listFragmentHTML` of the JSON answer (checked live on 2026-10-30; the plain `?page=N` HTML URL
returns page 1 again for every N, so it cannot be used to paginate). The fragment endpoint needs no
cookie or extra header. Past the end of the list it answers `{"eof": true, "listFragmentHTML": ""}`,
and the walk ends on the first page without an unseen id (rule 17).
"""

from urllib.parse import quote

from scrapy.http import Response

from take_jobs.infrastructure.scraping.parsers import infojobs
from take_jobs.infrastructure.scraping.parsers.common import ListingPage
from take_jobs.infrastructure.scraping.slug import slugify_term
from take_jobs.infrastructure.scraping.spiders.base import ListingSpider

FRAGMENT_PATH = "/mf-publicarea/VacancyList/GetVacancyListFragment"


class InfojobsSpider(ListingSpider):
    name = "infojobs"
    parse_page = staticmethod(infojobs.parse_listing)

    def _listing_url(self, term: str, page: int) -> str:
        return f"{self.base_url}/vagas-de-emprego-{slugify_term(term)}.aspx?page={page}"

    def first_page_url(self, term: str) -> str:
        return self._listing_url(term, 1)

    def next_page_url(self, term: str, listing: ListingPage, response: Response) -> str | None:
        page = self.states[term].pages + 1
        # Same encoding as the site's `encodeURIComponent(url)`.
        return f"{self.base_url}{FRAGMENT_PATH}?url={quote(self._listing_url(term, page), safe='')}"
