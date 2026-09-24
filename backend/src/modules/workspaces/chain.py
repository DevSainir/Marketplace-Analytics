"""Which chain of ticks is the live one for a backfill lane.

A lane is a chain: each tick does one step and enqueues the next, so exactly one
tick should ever be in flight. Two things break that, and they compound. The
watchdog restarts a lane it believes dead; and a worker recreated mid-tick has
its unacknowledged task redelivered by the broker. Either way the restart and
the original both continue, and from then on the lane runs as two chains that
cannot see each other.

Observed on NEVA 2026-09-12: two chains ticked the same P&L lane — trace
``c2c87118…`` and ``a657733d…`` — and each independently declared it finished,
an hour and a quarter apart. On an endpoint WB served once per fifteen minutes
(and on the one-a-minute finance-api just the same) a second chain does not
halve the walk; it spends half the budget re-fetching what the first already
holds, and doubles every conclusion drawn from a page.

So a chain carries a token, kept in Redis under the lane. A tick continues only
while its token is still the lane's. Anything that STARTS a chain — signup, the
watchdog, one lane handing on to the next — writes a fresh token and thereby
supersedes whatever was running, without having to find it first.

**Fails open**, like every other Redis-backed control here: a tick whose token
cannot be checked runs anyway. A duplicate chain wastes budget; a lane that
stops for good because a cache was briefly unreachable is the exact failure this
subsystem exists to prevent.
"""

from __future__ import annotations

import uuid

from src.core.logging import get_logger
from src.core.redis import get_redis
from src.modules.workspaces.models import BackfillLane

logger = get_logger(__name__)

#: How long a lane's token survives without a tick to refresh it.
#:
#: Longer than any lane's gap between ticks by a wide margin — the slowest is
#: the P&L lane at ~15.5 minutes — because the cost of expiring early is a
#: superseded chain wrongly adopting the lane, while the cost of expiring late
#: is nothing at all: the next start overwrites the key regardless.
CHAIN_TTL_SECONDS = 24 * 60 * 60


def _key(workspace_id: uuid.UUID, lane: BackfillLane) -> str:
    return f"workspaces:backfill:chain:{workspace_id}:{lane}"


async def claim_chain(
    workspace_id: uuid.UUID, lane: BackfillLane, token: str | None = None
) -> str | None:
    """The token this tick should carry on, or ``None`` if it was superseded.

    Args:
        workspace_id: The workspace being backfilled.
        lane: Which lane this tick belongs to.
        token: The chain token the tick was enqueued with. ``None`` means the
            tick is STARTING a chain rather than continuing one, which claims
            the lane and ends any chain already on it.

    Returns:
        The token to pass to the next tick, or ``None`` when a newer chain owns
        the lane and this tick should do nothing.
    """
    key = _key(workspace_id, lane)
    try:
        redis = get_redis()
        if token is None:
            fresh = uuid.uuid4().hex
            await redis.set(key, fresh, ex=CHAIN_TTL_SECONDS)
            return fresh
        current = await redis.get(key)
        if current is None:
            # No owner recorded — a flushed or restarted Redis, not a handover.
            # Adopting is right: refusing here would strand a healthy lane on a
            # cache outage, and the watchdog would then restart it anyway.
            await redis.set(key, token, ex=CHAIN_TTL_SECONDS)
            return token
        if current != token:
            return None
        await redis.expire(key, CHAIN_TTL_SECONDS)
        return token
    except Exception:
        logger.warning(
            "Could not read the backfill chain token for %s lane %s; continuing.",
            workspace_id,
            lane,
        )
        return token or uuid.uuid4().hex


__all__ = ["CHAIN_TTL_SECONDS", "claim_chain"]
