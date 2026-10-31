"""Scrapy settings built from the application settings (ADR-003, rule 25, invariants 7 and 9).

`infrastructure.scraping` never imports `take_jobs.config`, so the settings it needs are described
by a structural type that `take_jobs.config.Settings` satisfies.
"""

from typing import Any, Protocol

# Each request times out after this many seconds (rule 25).
DOWNLOAD_TIMEOUT_S = 30
# The crawl stops this many minutes before a run could be taken over (rules 13 and 25).
CRAWL_MARGIN_MINUTES = 10


class ScrapeSettings(Protocol):
    scrape_max_pages: int
    scrape_download_delay: float
    scrape_user_agent: str
    scrape_run_timeout_minutes: int
    log_level: str


def build_scrapy_settings(settings: ScrapeSettings) -> dict[str, Any]:
    return {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": settings.scrape_user_agent,
        # Per-site serialization: one request in flight, at least DOWNLOAD_DELAY apart.
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": settings.scrape_download_delay,
        "RANDOMIZE_DOWNLOAD_DELAY": False,  # deprecated since Scrapy 2.19; kept per UT-048
        "DOWNLOAD_DELAY_JITTER": 0,  # its replacement: never wait less than DOWNLOAD_DELAY
        "AUTOTHROTTLE_ENABLED": False,
        "DOWNLOAD_TIMEOUT": DOWNLOAD_TIMEOUT_S,
        "CLOSESPIDER_TIMEOUT": (settings.scrape_run_timeout_minutes - CRAWL_MARGIN_MINUTES) * 60,
        # Use whichever reactor the child process gets; Scrapy never installs an asyncio one.
        "TWISTED_REACTOR": None,
        # Scrapy never touches the database: no item pipeline does I/O.
        "ITEM_PIPELINES": {},
        "TELNETCONSOLE_ENABLED": False,
        "REMOTE_CONTROL_ENABLED": False,
        "LOG_LEVEL": "DEBUG" if settings.log_level == "DEBUG" else "WARNING",
    }
