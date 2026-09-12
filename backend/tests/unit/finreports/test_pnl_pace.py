"""How fast the P&L lane may ask, and why it is not a constant.

WB publishes "1 request per 15 minutes" for `reportDetailByPeriod`. That is not
what it enforces. Measured on NEVA 2026-09-12 from the rate bucket's own
`blocked_until`: a request 18 minutes after a successful one drew
`429 ... demands a 2762s wait` — a 46-minute penalty block.

The cost is asymmetric, which is the whole reason this adapts. Too slow loses
time in proportion; too fast loses it threefold, because the attempt is refused
AND punished. So the lane treats a refusal as evidence and a success as
permission, and it always errs toward the slow side.
"""

from __future__ import annotations

import pytest

from src.modules.finreports.tasks.backfill import pace

TOKEN = "a-statistics-token"


class _FakeRedis:
    def __init__(self, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.broken = broken

    async def get(self, key: str) -> str | None:
        if self.broken:
            raise ConnectionError("redis is down")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.store[key] = value


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(pace, "get_redis", lambda: fake)
    return fake


def test_the_floor_is_above_the_interval_that_was_punished() -> None:
    """18 minutes drew a 46-minute block, so 18 minutes is not a floor.

    The floor is where the lane returns after every good page, so setting it AT
    the measured failure would make the punished interval the resting state.
    """
    assert pace.PACE_FLOOR_SECONDS > 18 * 60


def test_a_fresh_lane_starts_slower_than_its_floor() -> None:
    """The first pages are the ones with no evidence behind them."""
    assert pace.PACE_DEFAULT_SECONDS > pace.PACE_FLOOR_SECONDS


def test_the_ceiling_stays_inside_the_watchdog_s_patience() -> None:
    """A lane slower than the staleness window gets restarted for being slow.

    That would be the pace fighting the watchdog: each restart claims the chain,
    the walk never settles, and both look correct in isolation.
    """
    from src.modules.workspaces.tasks import STALE_AFTER

    assert STALE_AFTER.total_seconds() > pace.PACE_CEILING_SECONDS


async def test_a_refused_page_widens_the_interval(redis: _FakeRedis) -> None:
    """The response to a penalty is to stop earning it."""
    before = await pace.read_pace(TOKEN)

    after = await pace.widen_pace(TOKEN)

    assert after > before
    assert await pace.read_pace(TOKEN) == after


async def test_a_served_page_eases_it_back(redis: _FakeRedis) -> None:
    """Otherwise one bad morning slows the lane for the rest of the walk."""
    widened = await pace.widen_pace(TOKEN)

    eased = await pace.ease_pace(TOKEN)

    assert eased < widened


async def test_widening_is_faster_than_easing(redis: _FakeRedis) -> None:
    """A refusal is evidence; one good page is not evidence it has passed.

    Symmetric steps would walk straight back into the interval that was just
    punished, which is how a 46-minute block becomes a recurring one.
    """
    start = await pace.read_pace(TOKEN)
    widened = await pace.widen_pace(TOKEN)
    await pace.ease_pace(TOKEN)
    once_eased = await pace.read_pace(TOKEN)

    assert once_eased > start, "one good page must not undo a refusal"
    assert widened - once_eased < widened - start


async def test_easing_never_goes_below_the_floor(redis: _FakeRedis) -> None:
    """A long quiet streak must not walk the lane back into the penalty."""
    for _ in range(50):
        await pace.ease_pace(TOKEN)

    assert await pace.read_pace(TOKEN) == pace.PACE_FLOOR_SECONDS


async def test_widening_never_passes_the_ceiling(redis: _FakeRedis) -> None:
    """Past the ceiling a lane is not slow, it is stopped — and gets restarted."""
    for _ in range(50):
        await pace.widen_pace(TOKEN)

    assert await pace.read_pace(TOKEN) == pace.PACE_CEILING_SECONDS


async def test_a_redis_outage_gives_a_safe_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failing open here must mean slow, not fast.

    The default is the conservative value precisely so that losing the learned
    pace cannot resurrect the interval that was earning penalty blocks.
    """
    monkeypatch.setattr(pace, "get_redis", lambda: _FakeRedis(broken=True))

    assert await pace.read_pace(TOKEN) == pace.PACE_DEFAULT_SECONDS


async def test_the_token_never_appears_in_the_key() -> None:
    """This string is logged, scanned and dumped by every Redis tool there is."""
    assert TOKEN not in pace._key(TOKEN)
