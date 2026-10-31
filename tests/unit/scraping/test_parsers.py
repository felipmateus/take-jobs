"""UT-030 to UT-039: the pure listing parsers, driven by trimmed live pages (2026-10-30)."""

import json

import pytest

from take_jobs.domain.models import ScrapedJob
from take_jobs.infrastructure.scraping.parsers import infojobs, vagas
from take_jobs.infrastructure.scraping.parsers.common import clean

VAGAS_PAGE = "https://www.vagas.com.br/vagas-de-python"
INFOJOBS_PAGE = "https://www.infojobs.com.br/vagas-de-emprego-python.aspx?page=1"


def vagas_card(
    external_id: str | None = "123",
    title: str | None = "Desenvolvedor Python",
    company: str | None = "ACME",
    href: str | None = "/vagas/v123/desenvolvedor-python",
) -> str:
    attrs = []
    if external_id is not None:
        attrs.append(f'data-id-vaga="{external_id}"')
    if title is not None:
        attrs.append(f'title="{title}"')
    if href is not None:
        attrs.append(f'href="{href}"')
    employer = f'<span class="emprVaga"> {company} </span>' if company is not None else ""
    return f"""
    <li class="vaga odd ">
      <a class="link-detalhes-vaga" {" ".join(attrs)}>link</a>
      {employer}
      <div class="detalhes"><p>Resumo com <mark>Python</mark> no texto</p></div>
      <div class="vaga-local"><i></i> Sao Paulo / SP <div class="tooltip-text">dica</div></div>
      <span class="data-publicacao"><i></i>09/10/2026</span>
    </li>"""


def infojobs_card(external_id: str = "55", title: str | None = "Dev Python") -> str:
    heading = f'<h2 class="js_vacancyTitle"> {title} </h2>' if title is not None else ""
    return f"""
    <div class="card"><div data-id="{external_id}" data-href="/vaga-de-dev__{external_id}.aspx"
         class="js_cardLink">
      <div class="text-medium small text-nowrap"> 28 out </div>
      {heading}
      <a class="text-body text-decoration-none"><span> ACME </span></a>
      <div class="mb-8"> Porto Alegre - RS<span hidden>, 0 Km de você.</span></div>
      <div class="d-inline-flex mb-8 text-medium"><div>A combinar</div></div>
      <div class="text-medium"> Resumo da vaga </div>
    </div></div>"""


def test_ut030_vagas_first_page_maps_every_field(read_fixture) -> None:
    page = vagas.parse_listing(read_fixture("vagas_python_p1.html"), VAGAS_PAGE)

    assert len(page.jobs) == 40
    assert page.jobs[0] == ScrapedJob(
        source="vagas",
        external_id="2838856",
        title="Analista de Business Intelligence",
        url="https://www.vagas.com.br/vagas/v2838856/analista-de-business-intelligence",
        company="Bom Futuro",
        location="Cuiabá / MT",
        description=(
            "áreas afins;Experiência em engenharia ou arquitetura de dados;SQL avançado e "
            "modelagem dimensional;Python de consumo (BI, monitoramentos e aplicações);Conduzir "
            "a migração de ETLs legados para pipelines em Python formatos colunares (Parquet);"
            "Orquestração de pipelines (Airflow, Prefect, Dagster ou similar);APIs REST em Python"
        ),
        published_label="09/10/2026",
    )
    for job in page.jobs:
        assert job.source == "vagas"
        assert job.external_id.isdigit()
        assert job.title
        assert job.url.startswith("https://www.vagas.com.br/vagas/v")
        assert job.company is None or job.company == job.company.strip()
        assert job.description is None or "<mark" not in job.description
        # The label is stored as displayed: a date such as 09/10/2026, or a relative label.
        assert job.published_label


def test_ut031_urls_resolve_against_the_page_url(read_fixture) -> None:
    html = read_fixture("vagas_python_p1.html")

    real = vagas.parse_listing(html, VAGAS_PAGE)
    local = vagas.parse_listing(html, "http://127.0.0.1:9999/vagas-de-python")

    assert real.next_url == "https://www.vagas.com.br/vagas-de-python?pagina=2&q=python"
    assert local.next_url == "http://127.0.0.1:9999/vagas-de-python?pagina=2&q=python"
    assert len(local.jobs) == 40
    assert all(job.url.startswith("http://127.0.0.1:9999/") for job in local.jobs)


def test_ut032_last_xhr_page_has_jobs_and_no_next(read_fixture) -> None:
    page = vagas.parse_listing(
        read_fixture("vagas_python_p2_xhr.html"),
        "https://www.vagas.com.br/vagas-de-python?pagina=2&q=python",
    )

    assert len(page.jobs) > 0
    assert page.next_url is None


def test_ut033_vagas_skips_card_without_id_and_keeps_missing_company_as_none() -> None:
    html = vagas_card(external_id=None) + vagas_card(external_id="124", company=None)

    page = vagas.parse_listing(html, VAGAS_PAGE)

    assert [job.external_id for job in page.jobs] == ["124"]
    assert page.jobs[0].company is None
    assert page.jobs[0].location == "Sao Paulo / SP"
    assert page.jobs[0].description == "Resumo com Python no texto"


def test_vagas_skips_card_without_title_or_link_target() -> None:
    html = vagas_card(title=None) + vagas_card(external_id="2", href=None) + vagas_card("3")

    page = vagas.parse_listing(html, VAGAS_PAGE)

    assert [job.external_id for job in page.jobs] == ["3"]


def test_ut034_infojobs_first_page_maps_every_field(read_fixture) -> None:
    page = infojobs.parse_listing(read_fixture("infojobs_python_p1.html"), INFOJOBS_PAGE)

    assert len(page.jobs) == 20
    assert page.next_url is None
    first = page.jobs[0]
    assert first.source == "infojobs"
    assert first.external_id == "11911899"
    assert first.title == "Desenvolvedor Python"
    assert first.company == "ISLA"
    assert first.location == "Porto Alegre - RS"
    assert first.published_label == "28 out"
    assert first.url == (
        "https://www.infojobs.com.br/vaga-de-desenvolvedor-python-em-rio-grande-do-sul"
        "__11911899.aspx"
    )
    assert first.description is not None
    assert first.description.startswith("Responsabilidades: Apoio em atividades")
    assert "\n" not in first.description


def test_infojobs_location_and_summary_come_from_their_own_lines() -> None:
    page = infojobs.parse_listing(infojobs_card(), INFOJOBS_PAGE)

    job = page.jobs[0]
    assert job.location == "Porto Alegre - RS"
    assert job.description == "Resumo da vaga"
    assert job.company == "ACME"


def test_ut035_infojobs_skips_card_without_title() -> None:
    html = infojobs_card("1", title=None) + infojobs_card("2")

    page = infojobs.parse_listing(html, INFOJOBS_PAGE)

    assert [job.external_id for job in page.jobs] == ["2"]


def fragment_body(html: str) -> str:
    return json.dumps({"eof": False, "listFragmentHTML": html})


def test_infojobs_fragment_response_maps_the_same_fields_as_the_html_page(read_fixture) -> None:
    """Review round 7, issue 001: pages 2+ are JSON from the list-fragment endpoint."""
    api_url = (
        "https://www.infojobs.com.br/mf-publicarea/VacancyList/GetVacancyListFragment"
        "?url=https%3A%2F%2Fwww.infojobs.com.br%2Fvagas-de-emprego-python.aspx%3Fpage%3D2"
    )

    page = infojobs.parse_listing(read_fixture("infojobs_python_p2_fragment.json"), api_url)

    assert len(page.jobs) == 20
    assert page.next_url is None
    first = page.jobs[0]
    assert first.source == "infojobs"
    assert first.external_id
    assert first.title
    assert first.company
    # A relative `data-href` resolves against the site origin, not against the endpoint path.
    assert first.url.startswith("https://www.infojobs.com.br/vaga-de-")
    assert first.published_label is not None


def test_infojobs_fragment_matches_the_html_parse_of_the_same_cards() -> None:
    cards = infojobs_card("1") + infojobs_card("2")

    from_html = infojobs.parse_listing(cards, INFOJOBS_PAGE)
    from_fragment = infojobs.parse_listing(fragment_body(cards), INFOJOBS_PAGE)

    assert from_fragment == from_html
    assert len(from_html.jobs) == 2


@pytest.mark.parametrize(
    "body", ['{"eof": true, "listFragmentHTML": ""}', '{"eof": true, "listFragmentHTML": null}']
)
def test_infojobs_end_of_list_fragment_is_zero_jobs(body: str) -> None:
    page = infojobs.parse_listing(body, INFOJOBS_PAGE)

    assert page.jobs == ()
    assert page.next_url is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("{not json", "Expecting property name"),
        ('{"eof": true}', "no listFragmentHTML"),
        ('{"listFragmentHTML": 5}', "not a string"),
    ],
    ids=["malformed", "key-missing", "not-a-string"],
)
def test_infojobs_unexpected_fragment_shape_raises_so_the_term_fails(
    body: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        infojobs.parse_listing(body, INFOJOBS_PAGE)


@pytest.mark.parametrize("parser", [vagas, infojobs], ids=["vagas", "infojobs"])
def test_ut036_empty_listing_is_zero_jobs_and_no_next(read_fixture, parser) -> None:
    page = parser.parse_listing(read_fixture("empty_listing.html"), "https://www.example.com/x")

    assert page.jobs == ()
    assert page.next_url is None


def test_ut037_xhr_page_with_more_pages_links_to_the_next_one(read_fixture) -> None:
    # Page 2 of `programador`: the term with the longest list on vagas.com (see memory/task_04.md).
    page = vagas.parse_listing(
        read_fixture("vagas_programador_p2_xhr.html"),
        "https://www.vagas.com.br/vagas-de-programador?pagina=2&q=programador",
    )

    assert len(page.jobs) > 0
    assert page.next_url is not None
    assert page.next_url.startswith("https://www.vagas.com.br/")
    assert "pagina=3" in page.next_url


def test_vagas_desenvolvedor_lists_a_single_page_of_ten(read_fixture) -> None:
    """Review round 7, issue 003: the live page says "10 vagas de emprego para desenvolvedor"."""
    html = read_fixture("vagas_desenvolvedor_p1.html")

    page = vagas.parse_listing(html, "https://www.vagas.com.br/vagas-de-desenvolvedor")

    assert "<h1>10 vagas de emprego para desenvolvedor</h1>" in html
    assert len(page.jobs) == 10
    assert page.next_url is None


def test_vagas_parser_also_accepts_a_bare_fragment() -> None:
    fragment = vagas_card("7") + '<a id="maisVagas" data-url="/vagas-de-x?pagina=3&amp;q=x"></a>'

    page = vagas.parse_listing(fragment, "https://www.vagas.com.br/vagas-de-x?pagina=2&q=x")

    assert [job.external_id for job in page.jobs] == ["7"]
    assert page.next_url == "https://www.vagas.com.br/vagas-de-x?pagina=3&q=x"


def test_ut038_nul_characters_are_removed_from_every_field() -> None:
    html = vagas_card(title="Dev\x00 Python", company="AC\x00ME")

    page = vagas.parse_listing(html, VAGAS_PAGE)

    assert page.jobs[0].title == "Dev Python"
    assert page.jobs[0].company == "ACME"
    assert clean("a\x00 b") == "a b"


@pytest.mark.parametrize(
    ("length", "kept"), [(64, True), (65, False)], ids=["64-chars-kept", "65-chars-skipped"]
)
@pytest.mark.parametrize("parser", ["vagas", "infojobs"])
def test_ut038_external_id_longer_than_64_characters_is_skipped(
    parser: str, length: int, kept: bool
) -> None:
    external_id = "9" * length
    if parser == "vagas":
        page = vagas.parse_listing(vagas_card(external_id=external_id), VAGAS_PAGE)
    else:
        page = infojobs.parse_listing(infojobs_card(external_id=external_id), INFOJOBS_PAGE)

    assert [job.external_id for job in page.jobs] == ([external_id] if kept else [])
