"""`_start_postgres` retries only the Ryuk port-mapping race (review round 7, issue 005).

The container class is replaced by a fake: no Docker is involved.
"""

from typing import ClassVar

import pytest

from tests import conftest as suite_conftest


class FakeContainer:
    outcomes: ClassVar[list[BaseException | None]] = []
    started: ClassVar[int] = 0
    stopped: ClassVar[int] = 0

    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def start(self) -> "FakeContainer":
        type(self).started += 1
        outcome = type(self).outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return self

    def stop(self) -> None:
        type(self).stopped += 1


@pytest.fixture(autouse=True)
def fake_container(monkeypatch: pytest.MonkeyPatch) -> type[FakeContainer]:
    FakeContainer.outcomes, FakeContainer.started, FakeContainer.stopped = [], 0, 0
    monkeypatch.setattr(suite_conftest, "PostgresContainer", FakeContainer)
    monkeypatch.setattr(suite_conftest.Reaper, "delete_instance", staticmethod(lambda: None))
    monkeypatch.setattr(suite_conftest.time, "sleep", lambda _seconds: None)
    return FakeContainer


def race(n: int = 1) -> ConnectionError:
    return ConnectionError(f"Port mapping for container {n} and port 8080 is not available")


def test_race_then_success_retries_and_warns(fake_container: type[FakeContainer]) -> None:
    fake_container.outcomes = [race(), None]

    with pytest.warns(RuntimeWarning, match=r"attempt 1/5 hit the Ryuk port-mapping race"):
        container = suite_conftest._start_postgres()

    assert isinstance(container, FakeContainer)
    assert fake_container.started == 2
    assert fake_container.stopped == 1  # the half-created attempt is cleaned up


def test_any_other_error_propagates_on_the_first_attempt(
    fake_container: type[FakeContainer],
) -> None:
    fake_container.outcomes = [RuntimeError("image not found"), None]

    with pytest.raises(RuntimeError, match="image not found"):
        suite_conftest._start_postgres()

    assert fake_container.started == 1


def test_a_connection_error_that_is_not_the_race_is_not_retried(
    fake_container: type[FakeContainer],
) -> None:
    fake_container.outcomes = [ConnectionError("connection refused"), None]

    with pytest.raises(ConnectionError, match="connection refused"):
        suite_conftest._start_postgres()

    assert fake_container.started == 1


def test_every_attempt_hitting_the_race_raises_the_last_chained_to_the_first(
    fake_container: type[FakeContainer],
) -> None:
    fake_container.outcomes = [race(n) for n in range(1, 6)]

    with (
        pytest.warns(RuntimeWarning) as warned,
        pytest.raises(ConnectionError, match="container 5") as raised,
    ):
        suite_conftest._start_postgres()

    assert fake_container.started == suite_conftest.START_ATTEMPTS
    assert len(warned) == suite_conftest.START_ATTEMPTS - 1
    assert raised.value.__cause__ is not None
    assert "container 1" in str(raised.value.__cause__)


def test_a_different_error_after_a_race_propagates_with_the_race_in_the_log(
    fake_container: type[FakeContainer],
) -> None:
    fake_container.outcomes = [race(), RuntimeError("name conflict")]

    with (
        pytest.warns(RuntimeWarning, match="Port mapping"),
        pytest.raises(RuntimeError, match="name conflict"),
    ):
        suite_conftest._start_postgres()

    assert fake_container.started == 2
