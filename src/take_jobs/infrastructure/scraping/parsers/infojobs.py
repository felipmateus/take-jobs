"""Infojobs listing parser (pure; `_spec.md` > Integration Points, field mapping).

Two body shapes carry the same cards. Page 1 is a full HTML page. Pages 2 and up come from the
site's list-fragment endpoint (`spiders/infojobs.py`), a JSON object whose `listFragmentHTML` holds
the cards. Infojobs exposes no next link: the spider asks for the next page and stops on the first
page that brings no unseen id (rule 17), so `next_url` is always `None` here.
"""

import json

from take_jobs.infrastructure.scraping.parsers.common import (
    ListingPage,
    build_job,
    build_selector,
    clean,
    resolve,
    text_of,
)

SOURCE_ID = "infojobs"


def fragment_html(body: str) -> str:
    """The card markup inside a list-fragment JSON response (empty past the end of the list)."""
    payload = json.loads(body)
    if not isinstance(payload, dict) or "listFragmentHTML" not in payload:
        raise ValueError("fragment response has no listFragmentHTML")
    html = payload["listFragmentHTML"]
    if html is None:
        return ""
    if not isinstance(html, str):
        raise ValueError("listFragmentHTML is not a string")
    return html


def parse_listing(body: str, page_url: str) -> ListingPage:
    """Parse a page-1 HTML page or a list-fragment JSON response (told apart by the first char)."""
    html = fragment_html(body) if body.lstrip().startswith("{") else body
    selector = build_selector(html)
    jobs = []
    for card in selector.css("div.js_cardLink"):
        # Exact-class children: `div.mb-8` and `div.text-medium` also match the attribute row
        # (`d-inline-flex mb-8 text-medium`) and the date, so a card without a location or summary
        # would otherwise pick up the wrong line.
        location_lines = card.xpath('./div[@class="mb-8"]/text()').getall()
        summaries = card.xpath('./div[@class="text-medium"]')
        job = build_job(
            source=SOURCE_ID,
            external_id=card.attrib.get("data-id"),
            title=text_of(card.css("h2.js_vacancyTitle")),
            url=resolve(page_url, card.attrib.get("data-href")),
            company=text_of(card.css("a.text-body.text-decoration-none")),
            location=next((line for line in map(clean, location_lines) if line), None),
            description=text_of(summaries[-1:]),
            published_label=text_of(card.css("div.text-medium.small.text-nowrap")),
        )
        if job is not None:
            jobs.append(job)
    return ListingPage(jobs=tuple(jobs), next_url=None)
