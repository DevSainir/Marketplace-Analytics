"""Which WB API family gets which bucket, and which endpoints differ inside it.

One surface is not one budget. WB publishes a limit per ENDPOINT, and the
families here are sized from the strictest endpoint each one contains — so an
endpoint WB meters more generously needs saying so explicitly, in the map its
factory passes down. Anything unlisted keeps the surface default, which is the
safe direction: a new endpoint arrives paced, not unpaced.

The mechanism these factories build lives in :mod:`gates`.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.core.config import Settings
from src.core.redis import get_redis
from src.integrations.wildberries.rate_limit.gates import (
    NullRateGate,
    RateGate,
    TokenBucketRateGate,
)

#: Advertising endpoints WB meters far more generously than ``/adv/v3/fullstats``,
#: whose 3-per-minute budget the surface default is sized from. Source: WB's own
#: published table, transcribed in
#: ``.claude/skills/wildberries-api/references/advertising.md``.
#:
#: Only the two campaign-discovery calls are listed. They are the ones a backfill
#: makes on the way to every fullstats call, and pacing them at the fullstats rate
#: is what made three concurrent ticks of one lane queue past the 120 s cap and
#: page (prod, 2026-09-11). ``/adv/v1/normquery/stats`` is in WB's table too but
#: stays on the default: nothing here needs it faster, and its published burst of
#: 20 is the one number in that table no measurement of ours has confirmed.
#: ``/adv/v1/budget`` is absent from the table altogether, so it keeps the
#: conservative default by the same rule — an unlisted endpoint is not a fast one.
ADVERTISING_ENDPOINT_BUCKETS: Mapping[str, tuple[int, float]] = {
    # 5 / s, min interval 200 ms, burst 5.
    "/adv/v1/promotion/count": (5, 0.2),
    "/api/advert/v2/adverts": (5, 0.2),
}


def analytics_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the analytics surface.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's analytics token — the bucket is per token, so
            one workspace's harvest never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="analytics",
        token=token,
        capacity=settings.wb_analytics_bucket_capacity,
        refill_seconds=settings.wb_analytics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )


def marketplace_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the marketplace (FBS) surface.

    Both FBS endpoints answered ``x-ratelimit-remaining: 20`` when measured on
    2026-08-13 — a far tighter budget than the analytics surface, and the
    harvest spends one token per enabled warehouse per run.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's marketplace token — the bucket is per token.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="marketplace",
        token=token,
        capacity=settings.wb_marketplace_bucket_capacity,
        refill_seconds=settings.wb_marketplace_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )


def statistics_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the statistics surface's settlement report.

    Sized from a live 429 on 2026-09-07 (see the settings comment): the walk's
    pages must be at least a minute apart, and WB answers a violation with a
    fifteen-minute penalty block rather than a Retry-After the ladder could
    honour — so the request must not be sent, not merely retried.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's statistics token — the bucket is per token, so
            one seller's settlement walk never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="statistics",
        token=token,
        capacity=settings.wb_statistics_bucket_capacity,
        refill_seconds=settings.wb_statistics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_statistics_max_queue_seconds,
    )


def settlement_walk_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the settlement walk's gate — the same bucket, a longer queue.

    :func:`statistics_rate_gate` refuses rather than waits, because the request
    it guards is made inside a transaction PostgreSQL closes after 300 s idle.
    The walk takes its token BEFORE opening that transaction, so waiting is
    exactly what it should do: one week of settlement rows is worth a quarter
    of an hour, and the alternative is asking anyway and restarting WB's window.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's statistics token — the bucket is per token.

    Returns:
        A gate over the same per-endpoint bucket as
        :func:`statistics_rate_gate`, willing to queue for a full refill.
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="statistics",
        token=token,
        capacity=settings.wb_statistics_bucket_capacity,
        refill_seconds=settings.wb_statistics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_statistics_walk_queue_seconds,
    )


def advertising_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the advertising surface.

    This surface is the one with two independent consumers on the same seller
    token: the nightly harvest sweeps every campaign, and the A/B rotation
    poller reads the running tests every few minutes. The bucket lives in
    Redis, so those two share one budget instead of discovering each other
    through 429s — which is exactly what happened when the poller was probed
    against an unpaced client.

    WB's published limit for ``/adv/v3/fullstats`` is 3 requests per minute
    with a 20-second minimum interval and a burst of ONE, so the default bucket
    is one token refilling every 20s.

    **A separate key is not a separate size, and that distinction cost a page.**
    This docstring used to say the looser campaign-discovery calls "do not spend
    the fullstats budget", which is true and beside the point: they got their own
    Redis key and the fullstats *bucket size*. ``/adv/v1/promotion/count`` is
    metered by WB at 5 a second and was paced by us at 3 a minute, so three
    concurrent backfill ticks of one lane — each making that one call before its
    fullstats call — queued past the 120 s cap and raised (prod, 2026-09-11).
    :data:`ADVERTISING_ENDPOINT_BUCKETS` is where an endpoint's real limit goes.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's advertising token — the bucket is per token, so
            one workspace's polling never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="advertising",
        token=token,
        capacity=settings.wb_advertising_bucket_capacity,
        refill_seconds=settings.wb_advertising_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
        endpoint_buckets=ADVERTISING_ENDPOINT_BUCKETS,
    )
