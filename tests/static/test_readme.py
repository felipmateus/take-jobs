"""UT-112: the README contract (FR-31, US-022)."""

import re

import pytest

from tests.static.support import ROOT

README = ROOT / "README.md"
METRICS_SQL = ROOT / "src" / "take_jobs" / "infrastructure" / "db" / "metrics.sql"
SPEC = ROOT / "docs" / "tasks" / "fastapi-refactor" / "_spec.md"

REQUIRED_HEADINGS = {
    "overview": r"overview",
    "running": r"running",
    "querying the api": r"querying the api",
    "configuration": r"configuration",
    "v1 to v2": r"v1\s*(?:→|->|to)\s*v2",
}


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line.lstrip("#").strip().lower() for line in text.splitlines() if line.startswith("#")]


@pytest.mark.parametrize("pattern", REQUIRED_HEADINGS.values(), ids=REQUIRED_HEADINGS.keys())
def test_ut112_has_required_heading(readme: str, pattern: str) -> None:
    assert any(re.fullmatch(pattern, heading) for heading in _headings(readme))


def test_ut112_shows_ci_badge_in_first_screen(readme: str) -> None:
    first_screen = "\n".join(readme.splitlines()[:25])

    assert "actions/workflows/ci.yml/badge.svg" in first_screen


def test_ut112_shows_one_command_start_in_first_screen(readme: str) -> None:
    first_screen = "\n".join(readme.splitlines()[:25])

    assert "docker compose up --build" in first_screen


def test_ut112_embeds_the_o5_query_pinned_in_the_spec(readme: str) -> None:
    sql = METRICS_SQL.read_text(encoding="utf-8").strip()
    spec_text = SPEC.read_text(encoding="utf-8")
    pinned = [line.strip() for line in sql.splitlines()]

    assert sql in readme
    # The same statement as in `_spec.md` > Monitoring, ignoring the fence indentation.
    spec_lines = [line.strip() for line in spec_text.splitlines()]
    start = spec_lines.index(pinned[0])
    assert spec_lines[start : start + len(pinned)] == pinned


def test_ut112_documents_configuration_surface(readme: str) -> None:
    for needle in (".env.example", "API_PORT", "DATABASE_URL", "POSTGRES_USER"):
        assert needle in readme


def test_ut112_embeds_no_credential_url(readme: str) -> None:
    # A connection URL with embedded user info may only carry the development default.
    userinfo = re.compile(r"[a-z+]+" + re.escape("://") + r"(\S+)@")
    for match in userinfo.finditer(readme):
        assert match.group(1).partition(":")[2] == "take_jobs_dev"


def test_ut112_cites_v1_problems_by_file_path(readme: str) -> None:
    for path in ("src/sync_app/app.py", "src/sync_app/controllers/jobs_controller.py"):
        assert path in readme
