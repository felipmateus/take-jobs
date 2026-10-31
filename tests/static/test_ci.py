"""UT-111: the CI workflow contract (FR-29, US-021)."""

from pathlib import Path

import pytest
import yaml

from tests.static.support import ROOT

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(workflow: dict) -> list[str]:
    return [
        step["run"] for job in workflow["jobs"].values() for step in job["steps"] if "run" in step
    ]


def test_ut111_triggers_include_push_and_pull_request(workflow: dict) -> None:
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))

    assert {"push", "pull_request"} <= set(triggers)


def test_ut111_checkout_fetches_full_history(workflow: dict) -> None:
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout"))

    assert checkout["with"]["fetch-depth"] == 0


def test_ut111_runs_every_gate_in_order(workflow: dict) -> None:
    commands = _run_commands(workflow)
    expected = ["uv sync --frozen", "ruff format --check", "ruff check", "lint-imports", "pytest"]

    positions = [
        next(index for index, command in enumerate(commands) if needle in command)
        for needle in expected
    ]

    assert positions == sorted(positions)


def test_ut111_pytest_gates_coverage_at_80_percent(workflow: dict) -> None:
    pytest_command = next(command for command in _run_commands(workflow) if "pytest" in command)

    assert "--cov=take_jobs.domain" in pytest_command
    assert "--cov=take_jobs.application" in pytest_command
    assert "--cov-fail-under=80" in pytest_command


def test_ut111_runs_on_ubuntu_latest(workflow: dict) -> None:
    assert [job["runs-on"] for job in workflow["jobs"].values()] == ["ubuntu-latest"]


def test_ut111_workflow_file_is_where_github_looks() -> None:
    assert Path(WORKFLOW).is_file()
