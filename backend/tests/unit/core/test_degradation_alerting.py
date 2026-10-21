"""Unit tests for the security-control degradation ledger.

The problem was never "these controls fail open" — that is a decided trade-off.
It is that one Redis outage silently removes brute-force protection *and*
session revocation together, and without the ledger nothing is positioned to say
so. A control that logs its own exception from inside the request path turns an
outage into thousands of identical tracebacks: a flood no alert can bind to.

These cases pin the three behaviours that make the difference: a degradation is
announced once rather than per request, two simultaneous degradations raise
their own louder event, and the controls still fail *open* throughout — the
alerting must not have quietly become a new way to lock everybody out.
"""

from __future__ import annotations

import logging

import pytest
from redis.exceptions import RedisError

from src.core.degradation import (
    CONTROL_AUTH_RATE_LIMIT,
    CONTROL_SESSION_REVOCATION,
    EVENT_COMBINED,
    EVENT_DEGRADED,
    EVENT_RECOVERED,
    DegradationLedger,
)
from src.core.ratelimit import consume_budget


class FakeClock:
    """A monotonic clock the test advances by hand.

    Injected so the cooldown and correlation windows can be exercised in
    microseconds instead of minutes.
    """

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current fake time, in seconds."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move time forward."""
        self.now += seconds


def _ledger(clock: FakeClock) -> DegradationLedger:
    """Build a ledger on the fake clock with short, legible windows."""
    return DegradationLedger(clock=clock, cooldown_seconds=60.0, correlation_window_seconds=120.0)


def _events(caplog: pytest.LogCaptureFixture, token: str) -> list[logging.LogRecord]:
    """Return the records carrying a given event token.

    Matched on the ``event`` FIELD rather than on the rendered sentence. That
    is the thing an alert rule binds to, so it is the thing
    worth asserting on — a test that reads the prose would keep passing after a
    change that left every rule matching nothing.
    """
    return [r for r in caplog.records if getattr(r, "event", None) == token]


def _controls_in(record: logging.LogRecord) -> list[str]:
    """Return the control names a record names, however many it carries."""
    single = getattr(record, "control", None)
    if single is not None:
        return [single]
    return list(getattr(record, "controls", []))


def test_first_degradation_is_announced_once(caplog: pytest.LogCaptureFixture) -> None:
    """A control that starts failing open says so — exactly one record."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="ConnectionError: refused")

    # Assert
    announcements = _events(caplog, EVENT_DEGRADED)
    assert len(announcements) == 1
    assert _controls_in(announcements[0]) == [CONTROL_AUTH_RATE_LIMIT]


def test_a_flood_of_reports_inside_the_cooldown_stays_one_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point: 500 failing requests are one outage, not 500 alerts."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        for _ in range(500):
            ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="ConnectionError: refused")
            clock.advance(0.1)

    # Assert
    assert len(_events(caplog, EVENT_DEGRADED)) == 1


def test_an_ongoing_outage_repeats_after_the_cooldown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A heartbeat proves the outage is still happening, rather than forgotten."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")
        clock.advance(61.0)
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")

    # Assert
    assert len(_events(caplog, EVENT_DEGRADED)) == 2


def test_two_controls_down_together_raise_their_own_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The actual risk: the *combination* of the two."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")
        clock.advance(5.0)
        ledger.report_degraded(CONTROL_SESSION_REVOCATION, detail="down")

    # Assert
    combined = _events(caplog, EVENT_COMBINED)
    assert len(combined) == 1
    named = _controls_in(combined[0])
    assert CONTROL_AUTH_RATE_LIMIT in named
    assert CONTROL_SESSION_REVOCATION in named


def test_one_control_alone_never_raises_the_combined_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A single fail-open control is the accepted trade-off, not an emergency."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        for _ in range(10):
            ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")
            clock.advance(61.0)

    # Assert
    assert _events(caplog, EVENT_COMBINED) == []


def test_degradations_far_apart_are_not_simultaneous(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two outages an hour apart are two incidents, not one compound one."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")
        clock.advance(3600.0)
        ledger.report_degraded(CONTROL_SESSION_REVOCATION, detail="down")

    # Assert
    assert _events(caplog, EVENT_COMBINED) == []
    assert ledger.degraded_controls() == (CONTROL_SESSION_REVOCATION,)


def test_recovery_is_announced_and_rearms_the_alert(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A control that comes back says so, and the next failure is news again."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down")
        ledger.report_healthy(CONTROL_AUTH_RATE_LIMIT)
        clock.advance(1.0)
        ledger.report_degraded(CONTROL_AUTH_RATE_LIMIT, detail="down again")

    # Assert
    assert len(_events(caplog, EVENT_RECOVERED)) == 1
    assert len(_events(caplog, EVENT_DEGRADED)) == 2
    assert ledger.degraded_controls() == (CONTROL_AUTH_RATE_LIMIT,)


def test_reporting_health_on_a_healthy_control_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Called on every successful request, so silence is the whole requirement."""
    # Arrange
    clock = FakeClock()
    ledger = _ledger(clock)

    # Act
    with caplog.at_level(logging.WARNING):
        for _ in range(100):
            ledger.report_healthy(CONTROL_AUTH_RATE_LIMIT)

    # Assert
    assert caplog.records == []


class UnreachableRedis:
    """A Redis stand-in that is down, the way an outage presents to a caller."""

    async def incr(self, key: str) -> int:
        """Fail the way a severed connection does."""
        raise RedisError("Connection refused")

    async def expire(self, key: str, seconds: int) -> bool:
        """Never reached; present so the stand-in matches the surface used."""
        raise RedisError("Connection refused")


async def test_the_rate_limiter_still_fails_open_and_now_reports_it(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability is unchanged; the difference is that somebody is told."""
    # Arrange. A fresh ledger as well as a dead Redis: the process-wide one
    # carries state, and a cooldown left over from another test would suppress
    # exactly the record this asserts on.
    monkeypatch.setattr("src.core.redis._redis", UnreachableRedis())
    monkeypatch.setattr("src.core.degradation._ledger", DegradationLedger())

    # Act
    with caplog.at_level(logging.WARNING):
        allowed = await consume_budget(scope="auth", subject="1.2.3.4", limit=1, window_seconds=60)

    # Assert
    assert allowed is True, "the limiter must keep failing open, not lock the door"
    assert _events(caplog, EVENT_DEGRADED)
