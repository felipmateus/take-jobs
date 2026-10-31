"""The production `Clock`."""

from datetime import UTC, datetime


class SystemClock:
    """Implements the `Clock` port with the system time (timezone-aware UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)
