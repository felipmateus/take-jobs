"""Helpers shared by the static repository-contract tests (Compose, `.env.example`)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"

DOCKER_AVAILABLE = shutil.which("docker") is not None


def load_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def clean_environment() -> dict[str, str]:
    """The process environment without any key `.env.example` defines, so a developer's shell
    cannot change what Compose renders."""
    keys = set(parse_env_file(ENV_EXAMPLE))
    return {k: v for k, v in os.environ.items() if k not in keys}


def compose_config(
    project_dir: Path, *, env_file_text: str | None = None
) -> subprocess.CompletedProcess:
    """Render `docker-compose.yml` as JSON from a scratch project directory, so a `.env` of the
    working copy never leaks in. `env_file_text` becomes that directory's `.env`."""
    shutil.copy(COMPOSE_FILE, project_dir / "docker-compose.yml")
    if env_file_text is not None:
        (project_dir / ".env").write_text(env_file_text, encoding="utf-8")
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_dir),
            "-f",
            str(project_dir / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env=clean_environment(),
        check=False,
    )


INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}")
