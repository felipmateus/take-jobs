"""vagas.com listing parser (pure; `_spec.md` > Integration Points, field mapping).

The follow-up pages come from an XHR call whose response is a full HTML page in practice, but
the card and next-link selectors below work on a bare fragment too.
"""

from take_jobs.infrastructure.scraping.parsers.common import (
    ListingPage,
    build_job,
    build_selector,
    clean,
    resolve,
    text_of,
)

SOURCE_ID = "vagas"


def parse_listing(html: str, page_url: str) -> ListingPage:
    selector = build_selector(html)
    jobs = []
    for card in selector.css("li.vaga"):
        link = card.css("a.link-detalhes-vaga")
        if not link:
            continue
        job = build_job(
            source=SOURCE_ID,
            external_id=link[0].attrib.get("data-id-vaga"),
            title=link[0].attrib.get("title"),
            url=resolve(page_url, link[0].attrib.get("href")),
            company=text_of(card.css("span.emprVaga")),
            # Direct text only: the tooltip inside `div.vaga-local` is not part of the location.
            location=clean(" ".join(card.css("div.vaga-local::text").getall())),
            description=text_of(card.css("div.detalhes p")),
            published_label=text_of(card.css("span.data-publicacao")),
        )
        if job is not None:
            jobs.append(job)
    next_url = resolve(page_url, selector.css("a#maisVagas::attr(data-url)").get())
    return ListingPage(jobs=tuple(jobs), next_url=next_url)
