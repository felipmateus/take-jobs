"""Source registry: adding a site means one parser, one spider and one entry here (US-007)."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

import scrapy

from take_jobs.infrastructure.scraping.spiders.infojobs import InfojobsSpider
from take_jobs.infrastructure.scraping.spiders.vagas import VagasSpider


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    id: str  # "vagas" | "infojobs"
    spider: type[scrapy.Spider]  # walks every term itself; top-level class, so spawn can pickle it
    base_url: str  # real site origin, e.g. "https://www.vagas.com.br"


SOURCES: Mapping[str, SourceDefinition] = MappingProxyType(
    {
        "vagas": SourceDefinition("vagas", VagasSpider, "https://www.vagas.com.br"),
        "infojobs": SourceDefinition("infojobs", InfojobsSpider, "https://www.infojobs.com.br"),
    }
)


def with_base_url(
    sources: Mapping[str, SourceDefinition], base_url: str
) -> Mapping[str, SourceDefinition]:
    """Test seam: the same sources pointed at a local fixture server (FR-30). Not a config key."""
    return {key: replace(source, base_url=base_url) for key, source in sources.items()}
