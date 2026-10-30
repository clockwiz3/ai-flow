"""Injectable notion of "today".

Business rules depend on the current date (no bookings in the past, default return
date, ...). Services never call ``date.today()`` directly; they receive a ``Clock``
so tests can pin the date.
"""

from datetime import date, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that can tell the current calendar date."""

    def today(self) -> date: ...


class SystemClock:
    """Clock backed by the host system date."""

    def today(self) -> date:
        return date.today()


class FixedClock:
    """Clock frozen at a given date; can be moved forward explicitly."""

    def __init__(self, day: date) -> None:
        self._day = day

    def today(self) -> date:
        return self._day

    def set(self, day: date) -> None:
        """Jump to an arbitrary date."""
        self._day = day

    def advance(self, days: int = 1) -> date:
        """Move the clock forward by ``days`` and return the new date."""
        self._day = self._day + timedelta(days=days)
        return self._day
