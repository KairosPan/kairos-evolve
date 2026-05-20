"""Clock abstraction. RealClock for production, FakeClock for tests.

Anything that uses `datetime.now(UTC)` directly is hard to test because
time is non-deterministic. Inject a `Clock` and call `clock.now()` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeClock:
    """Manual clock for tests. Call .tick() to advance."""

    _current: datetime

    def now(self) -> datetime:
        return self._current

    def tick(self, delta: timedelta) -> None:
        self._current = self._current + delta


__all__ = ["Clock", "FakeClock", "RealClock"]
