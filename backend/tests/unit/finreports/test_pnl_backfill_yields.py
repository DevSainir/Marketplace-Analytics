"""The fresh report outranks the history, and the token only serves one of them.

WB meters `reportDetailByPeriod` at roughly four requests an hour per token, and
two walks want it: the hourly harvest, collecting the report WB published this
morning, and the backfill, filling months that have been missing for months.
Whoever asks first takes the window.

Until now that ordering was luck. On 2026-09-14 the harvest happened to take
09:54 and the backfill's next tick was refused — the right outcome by accident.
Had the backfill asked first, the report a seller opens the app to see would
have waited an hour behind history nobody was waiting for.

The monitoring lanes have yielded to their own harvest since they were written.
These pin the same rule onto the settlement lane.
"""

from __future__ import annotations

import pytest

from src.modules.finreports.constants import HARVEST_LOCK_KEY, HARVEST_LOCK_TTL_SECONDS
from src.modules.finreports.tasks import backfill


class _FakeRedis:
    def __init__(self, held: bool = False, broken: bool = False) -> None:
        self.held = held
        self.broken = broken

    async def exists(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis is down")
        return 1 if (self.held and key == HARVEST_LOCK_KEY) else 0


async def test_the_backfill_stands_aside_while_the_harvest_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: the fresh report gets the window."""
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(held=True))

    assert await backfill._harvest_is_running() is True


async def test_a_free_lock_does_not_hold_the_backfill_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yielding to a harvest that is not running would just be a slower lane."""
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(held=False))

    assert await backfill._harvest_is_running() is False


async def test_a_redis_outage_lets_the_backfill_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail open, like every other Redis-backed control here.

    A backfill running during a cache outage is a smaller problem than one that
    stops for good because it could not ask a question — and the rate gate still
    stands between it and WB either way.
    """
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(broken=True))

    assert await backfill._harvest_is_running() is False


def test_the_yield_outlasts_the_lock_it_is_waiting_on() -> None:
    """A tick that wakes while the harvest still holds the lock has wasted a trip.

    Worse, it re-enqueues from there — so a yield shorter than the lock turns
    into a sequence of them, and the lane can spend a whole harvest window
    waking up to the same closed door.
    """
    assert backfill._YIELD_SECONDS > HARVEST_LOCK_TTL_SECONDS
