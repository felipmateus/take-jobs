"""IT-012 (secret scan): no committed credentials.

A pattern hit fails the test with the file and line only; the captured value is never printed.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "secrets"
THIS_MODULE = Path(__file__).resolve()

PATTERNS = (
    re.compile(r"(?i)(password|passwd|pwd|secret|token)\s*[:=]\s*[\"']?([^\s\"'#,]+)"),
    re.compile(r"://[^:/\s@]+:([^@\s]+)@"),
)
# `str` is the type annotation of `postgres_password: str` and `token: str` in the sources, the
# only identifier-shaped capture that is certainly not a credential.
ALLOWED_VALUES = {"take_jobs_dev", "change-me", "null", "str"}


def is_allowed(value: str) -> bool:
    return (
        value in ALLOWED_VALUES
        or (value.startswith("${") and value.endswith("}"))
        or (value.startswith("<") and value.endswith(">"))
    )


def scan_text(text: str) -> list[int]:
    """Line numbers (1-based) holding a captured value that is not allowed."""
    hits: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in PATTERNS:
            if any(not is_allowed(match.groups()[-1]) for match in pattern.finditer(line)):
                hits.append(number)
                break
    return hits


def scanned_files() -> list[Path]:
    """Tracked files plus the ones about to be tracked (untracked and not ignored), which
    includes `.env.example`, minus the documentation and the scan's own module and fixtures."""
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    files: list[Path] = []
    for name in filter(None, listing.split("\0")):
        path = ROOT / name
        relative = path.relative_to(ROOT)
        if not path.is_file():
            continue
        if relative.parts[0] == "docs" and path.suffix == ".md":
            continue
        if path.resolve() == THIS_MODULE or FIXTURES in path.resolve().parents:
            continue
        files.append(path)
    return files


def find_leaks(path: Path) -> list[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []  # binary file
    return scan_text(text)


def test_it012_secret_scan_passes_on_the_repository() -> None:
    files = scanned_files()
    assert ROOT / ".env.example" in files
    assert ROOT / "docker-compose.yml" in files

    leaks = [f"{path.relative_to(ROOT)}:{line}" for path in files for line in find_leaks(path)]

    assert not leaks, f"possible credentials at: {', '.join(leaks)}"


def test_it012_secret_scan_flags_the_leak_fixture() -> None:
    leak = FIXTURES / "leak.env"

    assert [f"{leak.name}:{line}" for line in find_leaks(leak)] == ["leak.env:1"]


def test_it012_secret_scan_accepts_the_ok_fixture() -> None:
    assert find_leaks(FIXTURES / "ok.env") == []


@pytest.mark.parametrize(
    "line",
    [
        "POSTGRES_PASSWORD=${POSTGRES_PASSWORD-take_jobs_dev}",
        "password: <redacted>",
        "secret=change-me",
        "token = null",
        "DATABASE_URL=postgresql://u:${DB_PASSWORD}@h/db",
    ],
)
def test_it012_secret_scan_allows_placeholders(line: str) -> None:
    assert scan_text(line) == []


@pytest.mark.parametrize(
    "line",
    ["api_token: abc123", "PASSWORD='hunter2'", "postgresql://u:hunter2@h/db"],
)
def test_it012_secret_scan_flags_literals(line: str) -> None:
    assert scan_text(line) == [1]
