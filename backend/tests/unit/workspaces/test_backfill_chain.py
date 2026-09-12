"""Only one chain of ticks may own a backfill lane.

A lane is a chain of self-enqueueing ticks, and two things fork it: the watchdog
restarting a lane it believes dead, and the broker redelivering the
unacknowledged tick of a worker that was recreated mid-step. Both happened to
NEVA on 2026-09-12 — two chains, ``c2c87118…`` and ``a657733d…``, walked the same
P&L lane and each declared it finished, 78 minutes apart.

On an endpoint WB serves once per fifteen minutes that is not redundancy. The
two chains split one budget, so the walk runs at half speed while looking
healthy from either side.
"""

from __future__ import annotations

import uuid

import pytest

from src.modules.workspaces import chain
from src.modules.workspaces.models import BackfillLane

WS = uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d")
LANE = BackfillLane.PNL


class _FakeRedis:
    """Enough Redis for a token. TTLs are accepted and ignored — expiry is not
    what any of these tests are about."""

    def __init__(self, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.broken = broken

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        if self.broken:
            raise ConnectionError("redis is down")
        return self.store.get(key)

    async def expire(self, key: str, seconds: int) -> None:
        if self.broken:
            raise ConnectionError("redis is down")


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(chain, "get_redis", lambda: fake)
    return fake


async def test_a_tick_with_no_token_takes_the_lane(redis: _FakeRedis) -> None:
    """Signup, the watchdog and a lane handing on all arrive without one."""
    token = await chain.claim_chain(WS, LANE)

    assert token
    assert redis.store[chain._key(WS, LANE)] == token


async def test_the_live_chain_keeps_going(redis: _FakeRedis) -> None:
    """The ordinary case, and the one a guard must not break."""
    token = await chain.claim_chain(WS, LANE)

    assert await chain.claim_chain(WS, LANE, token) == token


async def test_a_restart_supersedes_the_chain_it_was_replacing(redis: _FakeRedis) -> None:
    """The whole point.

    The watchdog cannot tell a dead lane from a slow one — that is why it waits
    forty-five minutes and still gets it wrong sometimes. So it does not have
    to: it claims the lane, and the tick it was wrong about retires itself the
    next time it wakes.
    """
    old = await chain.claim_chain(WS, LANE)
    new = await chain.claim_chain(WS, LANE)

    assert new != old
    assert await chain.claim_chain(WS, LANE, old) is None
    assert await chain.claim_chain(WS, LANE, new) == new


async def test_a_lane_is_not_stopped_by_a_redis_that_lost_the_key(redis: _FakeRedis) -> None:
    """A flushed Redis must not strand a healthy lane.

    Refusing here would stop the walk until the watchdog restarted it — trading
    a duplicate chain for forty-five minutes of nothing, which is the worse of
    the two.
    """
    assert await chain.claim_chain(WS, LANE, "a-token-nobody-recorded") == "a-token-nobody-recorded"


async def test_a_redis_outage_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same reasoning, harder failure: the guard is an optimisation, not a gate.

    A duplicate chain wastes WB budget. A lane that stops for good because a
    cache was briefly unreachable is the exact silent death the backfill
    subsystem has been fixed for twice.
    """
    monkeypatch.setattr(chain, "get_redis", lambda: _FakeRedis(broken=True))

    assert await chain.claim_chain(WS, LANE, "carry-on") == "carry-on"
    assert await chain.claim_chain(WS, LANE) is not None


async def test_two_lanes_of_one_workspace_do_not_share_a_chain(redis: _FakeRedis) -> None:
    """They run concurrently by design; one claiming must not retire the other."""
    pnl = await chain.claim_chain(WS, BackfillLane.PNL)
    await chain.claim_chain(WS, BackfillLane.FUNNEL)

    assert await chain.claim_chain(WS, BackfillLane.PNL, pnl) == pnl
