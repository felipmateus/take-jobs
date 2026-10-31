"""Shared plumbing of the E2E journeys: collect through the CLI, then read through the API.

Both go through their public entry points (`main`, `create_app`) with the real composition and
the real database; only the sites are replaced by the fixture server (FR-30), and the crawl child
runs under the network guard.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from take_jobs.api.app import create_app
from take_jobs.api.schemas import RunDetailOut
from take_jobs.cli.main import build_cli_deps, main
from take_jobs.config import Settings
from take_jobs.infrastructure.scraping.registry import SOURCES, with_base_url
from tests.support.fixture_server import FixtureServer
from tests.support.socket_guard import install_test_socket_guard


@dataclass
class Collected:
    exit_code: int
    stdout: str
    stderr: str

    def run(self) -> RunDetailOut:
        """The run printed by `collect --json`, validated against the API's real model."""
        return RunDetailOut.model_validate_json(self.stdout)


@dataclass(frozen=True)
class Journey:
    """One database, one fixture server and the settings that tie them together."""

    database_url: str
    server: FixtureServer
    terms: str

    @property
    def settings(self) -> Settings:
        return Settings(_env_file=None, database_url=self.database_url, scrape_terms=self.terms)

    @property
    def sources(self) -> Mapping[str, Any]:
        return with_base_url(SOURCES, self.server.url)

    def collect(self, capsys: pytest.CaptureFixture[str], *args: str) -> Collected:
        """Run `take-jobs collect <args>` in this (main) thread, as the console script does."""
        capsys.readouterr()
        deps = build_cli_deps(
            self.settings, self.sources, child_initializer=install_test_socket_guard
        )
        code = main(["collect", *args], deps=deps)
        out, err = capsys.readouterr()
        return Collected(code, out, err)

    def api(self) -> TestClient:
        """Use as a context manager: the lifespan owns the engine."""
        return TestClient(create_app(self.settings, self.sources))


def json_of(collected: Collected) -> dict[str, Any]:
    return json.loads(collected.stdout)
