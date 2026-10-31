"""IT-012: `.env.example` <-> `Settings` <-> `docker-compose.yml`."""

import json
from pathlib import Path

import pytest

from take_jobs.config import Settings
from tests.static.support import (
    COMPOSE_FILE,
    DOCKER_AVAILABLE,
    ENV_EXAMPLE,
    INTERPOLATION,
    ROOT,
    compose_config,
    load_compose,
    parse_env_file,
)

EXTRA_KEYS = {"API_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}


def settings_env_names() -> set[str]:
    return {
        field.validation_alias
        for field in Settings.model_fields.values()
        if isinstance(field.validation_alias, str)
    }


def test_it012_env_example_keys_match_settings() -> None:
    assert set(parse_env_file(ENV_EXAMPLE)) == settings_env_names() | EXTRA_KEYS


def test_it012_env_example_values_are_the_settings_defaults() -> None:
    from_example = Settings(_env_file=ENV_EXAMPLE)
    defaults = Settings(_env_file=None)

    assert from_example.model_dump() == defaults.model_dump()


def test_it012_every_key_is_interpolated_with_the_example_default() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    example = parse_env_file(ENV_EXAMPLE)
    seen: dict[str, list[str]] = {}

    for match in INTERPOLATION.finditer(text):
        key, tail = match.groups()
        assert not tail.startswith(":"), f"colon form for {key}: empty values would be replaced"
        assert tail.startswith("-"), f"{key} has no default"
        seen.setdefault(key, []).append(tail[1:])

    assert set(seen) == set(example)
    for key, defaults in seen.items():
        assert set(defaults) == {example[key]}, key


def test_it012_db_has_no_published_port() -> None:
    assert "ports" not in load_compose()["services"]["db"]


def test_it012_env_is_gitignored() -> None:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in (line.strip() for line in lines)


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker CLI not available")
def test_it012_empty_value_passes_through_compose(tmp_path: Path) -> None:
    result = compose_config(tmp_path, env_file_text="RELEVANCE_EXCLUDE_KEYWORDS=\n")

    assert result.returncode == 0, result.stderr
    environment = json.loads(result.stdout)["services"]["scheduler"]["environment"]
    assert environment["RELEVANCE_EXCLUDE_KEYWORDS"] == ""
    # A key left unset keeps its default.
    assert environment["SCRAPE_CRON"] == "0 6 * * *"


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker CLI not available")
def test_it012_api_port_override_is_published(tmp_path: Path) -> None:
    result = compose_config(tmp_path, env_file_text="API_PORT=8001\n")

    assert result.returncode == 0, result.stderr
    ports = json.loads(result.stdout)["services"]["api"]["ports"]
    assert [(p["published"], p["target"]) for p in ports] == [("8001", 8000)]
