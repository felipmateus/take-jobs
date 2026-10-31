import pytest

from tests.support.fixture_server import FIXTURES


@pytest.fixture
def read_fixture():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read


@pytest.fixture(autouse=True)
def clean_scrape_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SCRAPE_MAX_PAGES",
        "SCRAPE_DOWNLOAD_DELAY",
        "SCRAPE_USER_AGENT",
        "SCRAPE_RUN_TIMEOUT_MINUTES",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
