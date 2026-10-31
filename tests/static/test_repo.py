"""UT-113 and UT-114: the `v1` tag and the SDD artifacts (FR-32, FR-33)."""

import shutil
import subprocess

import pytest

from tests.static.support import ROOT

SPEC_DIR = ROOT / "docs" / "tasks" / "fastapi-refactor"


def test_ut113_v1_tag_points_to_last_v1_commit() -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/tags/v1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("tag v1 not present")

    commit = subprocess.run(
        ["git", "rev-parse", "v1^{commit}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert commit.startswith("52018b3")


@pytest.mark.parametrize(
    "name",
    ["_prd.md", "_spec.md", "_user_stories.md", "_dx.md", "_tests.md", "_tasks.md"],
)
def test_ut114_spec_documents_exist(name: str) -> None:
    assert (SPEC_DIR / name).is_file()


def test_ut114_adrs_reviews_and_memory_exist() -> None:
    assert any((SPEC_DIR / "adrs").glob("adr-*.md"))
    assert any(path.is_dir() for path in SPEC_DIR.glob("reviews-*"))
    assert (SPEC_DIR / "memory").is_dir()
