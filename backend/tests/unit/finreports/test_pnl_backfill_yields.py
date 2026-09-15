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


class _Gate:
    def __init__(self, shut_for: float) -> None:
        self.shut_for = shut_for
        self.reserve_seen: float | None = None

    async def retry_after(self, _endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        self.reserve_seen = reserve_seconds
        return self.shut_for


async def test_an_open_window_is_not_padded_with_a_second_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A free token means the budget allows a request; waiting is then pure loss.

    This used to be floored at WB's published budget, which sounds safe and is
    not: the bucket is what enforces the budget, and it only reports zero when
    a token is genuinely free and has already outlived the background reserve.
    Adding a window on top of that just idles.

    What survives is a spin guard, for the case where the answer is not
    informative at all — Redis down, `retry_after` failing open to zero.
    """
    monkeypatch.setattr(backfill, "statistics_rate_gate", lambda *_a, **_k: _Gate(0.0))

    assert await backfill._next_page_delay("t") == backfill._MIN_PAGE_GAP_SECONDS


async def test_a_slow_tick_does_not_pay_for_its_own_duration_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug streaming would otherwise have introduced into its own fix.

    ``retry_after`` is read AFTER the page is ingested, so it already discounts
    the time the tick spent. A 300 s streamed page leaves ~740 s of the window
    to wait; a floor at WB's 930 s budget would make the lane wait 930 s more
    and hand back most of what streaming just saved — and the waste would grow
    with exactly the change meant to speed the walk up.
    """
    monkeypatch.setattr(backfill, "statistics_rate_gate", lambda *_a, **_k: _Gate(740.0))

    delay = await backfill._next_page_delay("t")

    assert delay == 740 + backfill._WAKE_MARGIN_SECONDS
    assert delay < backfill._NEXT_PAGE_SECONDS, "the published budget outranked the bucket"


async def test_a_block_is_waited_out_using_wb_s_own_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix for a six-fold self-inflicted slowdown.

    The interval used to be inferred from whether the last page arrived, which
    could not distinguish a penalty from someone else taking the window — so
    contention ratcheted it to 5400 s against an endpoint serving four requests
    an hour. WB states the number in ``x-ratelimit-retry``; the bucket already
    absorbs it, so the lane just reads it.
    """
    # 2762 s is the real penalty NEVA drew on 2026-09-12, read from the bucket's
    # own `blocked_until`. A 890 s block is NOT a useful case here: it is shorter
    # than the published budget, so the floor wins and the test would pass
    # whether or not the block was read at all.
    monkeypatch.setattr(backfill, "statistics_rate_gate", lambda *_a, **_k: _Gate(2762.0))

    delay = await backfill._next_page_delay("t")

    assert delay == 2762 + backfill._WAKE_MARGIN_SECONDS


async def test_the_wait_never_outlasts_the_watchdog_s_patience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise a lane obeying WB exactly gets restarted for obeying WB exactly,
    and the restart asks early — which is what WB answers with a penalty."""
    from src.integrations.wildberries.rate_limit.surfaces import (
        SETTLEMENT_PACE_CEILING_SECONDS,
    )

    monkeypatch.setattr(backfill, "statistics_rate_gate", lambda *_a, **_k: _Gate(99_999.0))

    assert await backfill._next_page_delay("t") == SETTLEMENT_PACE_CEILING_SECONDS


async def test_the_backfill_asks_as_a_reserving_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """The history walk must never be first in the queue for a window.

    The reserve is what makes that structural instead of a convention every
    future caller has to remember — and it has to reach the bucket, not just be
    defined. A gate asked without it hands the backfill the freshest slot of
    every window, which is the race this exists to end.
    """
    from src.integrations.wildberries.rate_limit.surfaces import BACKGROUND_RESERVE_SECONDS

    gate = _Gate(0.0)
    monkeypatch.setattr(backfill, "statistics_rate_gate", lambda *_a, **_k: gate)

    await backfill._next_page_delay("t")

    assert gate.reserve_seen == BACKGROUND_RESERVE_SECONDS


def test_the_tick_may_live_long_enough_to_finish_a_streamed_page() -> None:
    """The page size and the tick's lifetime are one decision, not two.

    A streamed request carries up to `_STREAM_LIMIT` rows — ~240 MB to download,
    parse, validate and upsert at 100 000. When that outgrows the soft limit the
    failure is not a slow tick but a SILENT one: `SoftTimeLimitExceeded` is not
    the `IntegrationError` the lane catches, so nothing is recorded and nothing
    re-enqueued, which is how this lane was lost for eleven hours on 2026-09-10.

    The budget below is deliberately generous — a minute per 10 000 rows against
    a measured ~60 MB per 25 000 — because the point is not to predict the
    duration but to make raising the page size force a look at this number.
    """
    from src.integrations.wildberries.clients.finance import WBFinanceClient

    seconds_needed = (WBFinanceClient._STREAM_LIMIT / 10_000) * 60

    assert seconds_needed <= backfill._TICK_SOFT_LIMIT_SECONDS, (
        f"a {WBFinanceClient._STREAM_LIMIT}-row page needs ~{seconds_needed:.0f}s of "
        f"headroom; the tick is killed at {backfill._TICK_SOFT_LIMIT_SECONDS}s"
    )


def test_a_hung_tick_is_still_restarted_rather_than_holding_a_slot() -> None:
    """Raising the limit must not outrun the thing that recovers a dead lane."""
    from datetime import timedelta

    from src.modules.workspaces.models import BackfillLane
    from src.modules.workspaces.tasks import _patience

    assert timedelta(seconds=backfill._TICK_SOFT_LIMIT_SECONDS) < _patience(BackfillLane.PNL)
