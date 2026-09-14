"""How long the P&L lane waits between pages, learned from WB's answers.

The interval was a constant — 15.5 minutes, from WB's published "1 request per
15 minutes" on ``reportDetailByPeriod``. Measured on NEVA 2026-09-12, that figure
is not what the endpoint enforces for a real token: a request **18 minutes**
after a successful one drew ``429 ... demands a 2762s wait``, a 46-minute
penalty block, read straight out of the bucket's ``blocked_until``.

That makes a fixed interval the wrong shape of answer, because the cost is
asymmetric. Ask too slowly and the walk takes proportionally longer. Ask too
quickly and the walk takes **three times** longer, since the attempt is both
refused and punished:

===================  ====================  ==============
Interval             Outcome               50 pages
===================  ====================  ==============
15.5 min (the old)   penalty, no data      ~38 hours
~25 min              page served           ~21 hours
===================  ====================  ==============

So the lane learns instead. A refused page widens the interval; a served one
eases it back toward the floor. The floor is above the number that was measured
to fail, not at it, because the next account's tolerance is its own and guessing
low is the expensive direction.

The pace lives beside the bucket in Redis, keyed by the same token fingerprint,
so it is shared by every worker and survives a deploy — a value relearned from
scratch after each restart would spend the whole morning rediscovering today's
penalty. **Fails open** to the default: a lane that cannot read its pace runs at
a safe one rather than stopping.
"""

from __future__ import annotations

import hashlib

from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.rate_limit.surfaces import SETTLEMENT_PACE_CEILING_SECONDS

logger = get_logger(__name__)

#: Never ask faster than this. Above the 18 minutes measured to draw a penalty,
#: not at it: the measurement is one account's tolerance on one morning, and the
#: floor is the value the lane will keep returning to.
PACE_FLOOR_SECONDS = 20 * 60

#: Never wait longer than this, however many refusals arrive.
#:
#: Defined beside the rate buckets rather than here, because the backfill
#: watchdog sizes its patience from the same number and ``workspaces`` may not
#: import ``finreports``. Keeping one module's constant as the other's bound is
#: what stops the pace and the watchdog from constraining each other: when the
#: cap sat below what WB wanted, the walk pinned against it and spent six of
#: every ten ticks earning refusals instead of fetching pages.
PACE_CEILING_SECONDS = SETTLEMENT_PACE_CEILING_SECONDS

#: Where a lane that has learned nothing yet starts. Deliberately above the
#: floor: the first pages of a fresh walk are the ones with no evidence behind
#: them, and a penalty there costs more than the minutes it saves.
PACE_DEFAULT_SECONDS = 25 * 60

#: Widen hard, ease gently. A refusal is evidence about WB's current mood and a
#: single success is not evidence it has passed — so the walk gives back the
#: interval over several good pages rather than all at once.
_WIDEN = 1.5
_EASE = 0.9

#: Long enough that the pace survives a quiet night, short enough that a token
#: WB has forgotten about does not inherit last month's penalty for ever.
_TTL_SECONDS = 7 * 24 * 60 * 60


def _key(token: str) -> str:
    """The pace key, fingerprinted exactly as the rate bucket's is.

    Never the token itself: this string is logged, scanned and dumped by every
    Redis tool anyone will ever point at the box.
    """
    fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
    return f"wb:pace:statistics:reportDetailByPeriod:{fingerprint}"


def _clamp(seconds: float) -> int:
    return int(min(PACE_CEILING_SECONDS, max(PACE_FLOOR_SECONDS, seconds)))


async def read_pace(token: str) -> int:
    """Seconds to wait before the next page for this token."""
    try:
        stored = await get_redis().get(_key(token))
    except Exception:
        logger.warning("Could not read the P&L pace; using the default.")
        return PACE_DEFAULT_SECONDS
    if stored is None:
        return PACE_DEFAULT_SECONDS
    try:
        return _clamp(float(stored))
    except ValueError:
        return PACE_DEFAULT_SECONDS


async def _write(token: str, seconds: int) -> int:
    try:
        await get_redis().set(_key(token), str(seconds), ex=_TTL_SECONDS)
    except Exception:
        logger.warning("Could not store the P&L pace; the next tick will use the default.")
    return seconds


async def widen_pace(token: str) -> int:
    """WB refused a page: wait longer before the next one.

    Called for a withheld page rather than for a gate refusal. A gate refusal is
    this system declining to send, which is the pacing already working — reacting
    to it would widen the interval on the evidence of its own caution.
    """
    widened = _clamp(await read_pace(token) * _WIDEN)
    logger.info("P&L pace widened to %ds after a refused page.", widened)
    return await _write(token, widened)


async def ease_pace(token: str) -> int:
    """WB served a page: edge back toward the floor."""
    return await _write(token, _clamp(await read_pace(token) * _EASE))


__all__ = [
    "PACE_CEILING_SECONDS",
    "PACE_DEFAULT_SECONDS",
    "PACE_FLOOR_SECONDS",
    "ease_pace",
    "read_pace",
    "widen_pace",
]
