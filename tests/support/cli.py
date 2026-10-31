"""Helpers shared by the CLI `collect` tests (unit and integration)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from take_jobs.domain.models import CombinationOutcome, ScrapedJob, ScrapeReport


def job(external_id: str, title: str, *, source: str = "vagas") -> ScrapedJob:
    return ScrapedJob(
        source=source,
        external_id=external_id,
        title=title,
        url=f"https://example.test/{source}/{external_id}",
        company="Acme",
        location="Sao Paulo - SP",
        description="Descricao",
        published_label="28 out",
    )


def outcome(
    source: str,
    term: str,
    jobs: Sequence[ScrapedJob] = (),
    *,
    pages: int = 1,
    error: str | None = None,
) -> CombinationOutcome:
    return CombinationOutcome(source=source, term=term, jobs=tuple(jobs), pages=pages, error=error)


def two_outcome_report(term: str = "python") -> ScrapeReport:
    """One vagas outcome with two jobs (one irrelevant) and an empty infojobs outcome."""
    return ScrapeReport(
        outcomes=(
            outcome(
                "vagas",
                term,
                [job("1", "Desenvolvedor Python Senior"), job("2", "Analista de Suporte")],
                pages=2,
            ),
            outcome("infojobs", term, [], pages=1),
        )
    )


@dataclass
class FakeScraper:
    """A `JobScraper` double: returns `report`, raises `error`, or runs `on_scrape` first."""

    report: ScrapeReport = field(default_factory=two_outcome_report)
    error: Exception | None = None
    on_scrape: Callable[[], None] | None = None
    scrape_calls: list[list[str]] = field(default_factory=list)
    interrupt_calls: int = 0

    def scrape(self, terms: Sequence[str]) -> ScrapeReport:
        self.scrape_calls.append(list(terms))
        if self.on_scrape is not None:
            self.on_scrape()
        if self.error is not None:
            raise self.error
        return self.report

    def interrupt(self) -> None:
        self.interrupt_calls += 1
