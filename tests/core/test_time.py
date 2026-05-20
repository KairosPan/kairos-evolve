"""Clock abstraction tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kairos_evolve.core.time import Clock, FakeClock, RealClock


def test_real_clock_returns_tz_aware_utc():
    now = RealClock().now()
    assert isinstance(now, datetime)
    assert now.tzinfo is UTC


def test_fake_clock_starts_at_provided():
    t0 = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    c = FakeClock(t0)
    assert c.now() == t0


def test_fake_clock_tick_advances():
    t0 = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    c = FakeClock(t0)
    c.tick(timedelta(seconds=30))
    assert c.now() == t0 + timedelta(seconds=30)


def test_fake_clock_is_clock():
    c: Clock = FakeClock(datetime.now(UTC))
    assert hasattr(c, "now")
