"""Helpers shared by the listing parsers: result type, text cleaning and sanitization."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from parsel import Selector, SelectorList

from take_jobs.domain.models import ScrapedJob

# Rule 27: a card whose site id is longer than this is skipped, like a card without an id.
MAX_EXTERNAL_ID_LENGTH = 64

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ListingPage:
    jobs: tuple[ScrapedJob, ...]
    next_url: str | None


def clean(value: str | None) -> str | None:
    """Remove NUL characters (rule 27), collapse whitespace and strip; empty becomes `None`."""
    if value is None:
        return None
    collapsed = _WHITESPACE.sub(" ", value.replace("\x00", "")).strip()
    return collapsed or None


def text_of(nodes: SelectorList[Selector]) -> str | None:
    """Cleaned `string()` of the first matched node, or `None` when nothing matched."""
    if not nodes:
        return None
    return clean(nodes[0].xpath("string(.)").get())


def resolve(page_url: str, value: str | None) -> str | None:
    """Resolve a URL taken from a page against the URL of that page (never a fixed origin)."""
    cleaned = clean(value)
    return urljoin(page_url, cleaned) if cleaned else None


def build_selector(html: str) -> Selector:
    # libxml2 stops or rewrites around NUL, so drop it before parsing (rule 27).
    return Selector(text=html.replace("\x00", ""))


def build_job(
    *,
    source: str,
    external_id: str | None,
    title: str | None,
    url: str | None,
    company: str | None,
    location: str | None,
    description: str | None,
    published_label: str | None,
) -> ScrapedJob | None:
    """Apply the skip rules (US-001.EC-1, rule 27); `None` means the card is skipped."""
    external_id = clean(external_id)
    title = clean(title)
    if not external_id or not title or url is None:
        return None
    if len(external_id) > MAX_EXTERNAL_ID_LENGTH:
        return None
    return ScrapedJob(
        source=source,
        external_id=external_id,
        title=title,
        url=url,
        company=clean(company),
        location=clean(location),
        description=clean(description),
        published_label=clean(published_label),
    )
