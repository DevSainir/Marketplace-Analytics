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


#: Analytics endpoints WB meters differently from ``sales-funnel``, which the
#: surface default is sized from.
#:
#: **The surface default was the only number here until 2026-09-21, and it was
#: wrong for four of the five endpoints we call.** Measured that day by
#: bursting each one on «Демо» and reading WB's own headers:
#:
#: ===================================== ======= ======= =======
#: endpoint                              burst   reset   retry
#: ===================================== ======= ======= =======
#: sales-funnel/products/history             3      60      20
#: stocks-report/wb-warehouses               1      20      20
#: ===================================== ======= ======= =======
#:
#: Only the first matches the default of three tokens refilling every twenty
#: times** WB's rate, and on this surface an overrun does not come back as a
#: clean 429 — it comes back as HTTP 500 or a socket held open until the
#: client's own timeout, which reads like a WB outage rather than like our
#: mistake.
#:
#: are deliberately absent and keep the default: unmeasured means paced
#: conservatively, which is the safe direction.
ANALYTICS_ENDPOINT_BUCKETS: Mapping[str, tuple[int, float]] = {
    "/api/analytics/v1/stocks-report/wb-warehouses": (1, 20.0),
    # Burst five, then one a minute — WB's `reset: 300` over a burst of 5.
    # The harvest asks for one report per workspace per run, so the burst is
    # never spent; what matters is that a retry cannot fire inside the minute.
}


#: Statistics endpoints WB meters far more generously than
#: ``/api/v5/supplier/reportDetailByPeriod``, whose ONE request per ~15 minutes
#: the surface default is sized from.
#:
#: Only the orders feed is listed, and only because the `guide` capture walks it
#: daily. Measured live 2026-09-12: it answers ``x-ratelimit-limit: 10`` where
#: ``supplier/sales`` answers ``1``. Left on the surface default it would take
#: sixteen minutes per page — not because WB says so, but because we would be
#: pacing a ten-a-minute endpoint at the settlement report's rate. One token per
#: 20 s is three a minute: comfortably inside WB's limit and still slow enough
#: that a runaway walk cannot become a burst.
#:
#: The settlement walk is untouched by this — the bucket is keyed per endpoint,
#: so a path that is not listed here keeps the strict default it has always had.
#: That correction is also why the rest of this note reads oddly: it argued
#: from «ten a minute» and reached the right shape for the wrong reason. One
#: token per 20 s was chosen as «comfortably inside WB's limit» and was in fact
#: three times outside it.
#:
#: ``supplier/sales`` is listed for the opposite reason to ``supplier/orders``:
#: not to speed it up, but because it was PACED BY NOTHING AT ALL until
#: 2026-09-15 (``WBStatisticsClient`` passed no gate), and the surface default it
#: would otherwise inherit is the settlement report's one-per-960-seconds — which
#: would stall every harvest for sixteen minutes.
#:
#: One per minute is WB's published figure for it and costs the harvest nothing:
#: a run makes exactly ONE sales call per workspace. What it does stop is a
#: person leaning on «Обновить» — every press fires this account-wide feed, and
#: it is the harshest limiter WB exposes (a 39-second 429 backoff, measured).
STATISTICS_ENDPOINT_BUCKETS: Mapping[str, tuple[int, float]] = {
    # Ten tokens, one back every minute. NOT ten a minute, which is how
    # `x-ratelimit-limit: 10` was read on 2026-09-12 and what this entry said
    # until 2026-09-21: burst and rate are different numbers, and only the
    # 429 carries the second one. Measured on «Демо» that day —
    # `limit: 10, reset: 599, retry: 59` — so the refill is one per minute and
    # the old pacing of one per twenty seconds was three times WB's rate.
    "/api/v1/supplier/orders": (10, 60.0),
    "/api/v1/supplier/sales": (1, 60.0),
}

#: The slowest interval the settlement walk may pace itself to, in seconds.
#:
#: Lives here rather than beside the walk because two modules need it and they
#: may not import each other: ``finreports`` widens the walk's interval up to
#: this, and ``workspaces`` sizes the backfill watchdog's patience from it. A
#: watchdog less patient than the pace is permitted to be restarts a lane for
#: being exactly as slow as it was told to be — and on this endpoint the restart
#: then asks early, which is what WB answers with a penalty block.
#:
#: 90 minutes because the published ``x-ratelimit-reset: 917`` is a floor rather
#: than the enforced tolerance. Measured on NEVA 2026-09-12/14: 18 minutes after a
#: good page still drew a 2762 s penalty, and with the cap at 40 minutes the walk
#: sat pinned against it — four pages served against six refusals in six hours,
#: the pace trying to widen past a ceiling it was not allowed to cross.
SETTLEMENT_PACE_CEILING_SECONDS = 90 * 60

#: How long a background walk must let a token sit before it may take it.
#:
#: The settlement endpoint serves about four requests an hour and several things
#: want them: the hourly harvest, a seller pressing «Обновить», and the history
#: backfill. Without an order they simply race, and the loser is whoever asked
#: second — which on 2026-09-12 was the fresh report, waiting behind history
#: nobody needed today.
#:
#: A reserve makes the order structural rather than a convention each caller has
#: to remember. It costs the backfill up to two minutes per window and cannot
#: cost the harvest anything. It does NOT change how many requests leave — the
#: bucket alone decides that — only who gets them when two callers want the same
#: one, so it is a courtesy, not a second limiter.
BACKGROUND_RESERVE_SECONDS = 120.0


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
        endpoint_buckets=ANALYTICS_ENDPOINT_BUCKETS,
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

    **The bucket is per token; a penalty block is not** (``shared_block``).
    Five tokens have probed this surface within the same second, twenty-one
    times a day, for months without being refused — so the ordinary budget is
    very probably metered per token. But on 2026-09-17 five distinct
    fingerprints ended up holding block expiries 0.77 s apart, which is one
    refusal seen five times rather than five refusals. The fleet walk is
    sequential, so per-token blocks turn that into a cascade: every seller in
    turn earns its own escalating block from the same shut door.

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
        endpoint_buckets=STATISTICS_ENDPOINT_BUCKETS,
        shared_block=True,
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
        endpoint_buckets=STATISTICS_ENDPOINT_BUCKETS,
        shared_block=True,
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


def catalogue_rate_gate(settings: Settings, *, token: str, surface: str) -> RateGate:
    """Build the pacing gate for one of the «catalogue» surfaces.

    Content, prices and common (tariffs) are one family here because WB meters
    them identically: all three answered ``x-ratelimit-limit: 5`` on 2026-09-15,
    and a burst against common-api showed a five-deep bucket refilling one token
    per second. They stay SEPARATE keys — ``surface`` is part of the Redis key —
    because they are separate budgets at WB; only the size is shared.

    None of the three was paced at all before that date. ``BaseWBClient``
    defaults its gate to :class:`NullRateGate`, so a client that never passed one
    was exempt without anything saying so, and the three of them run on every
    harvest.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's token for this surface — the bucket is per token.
        surface: Key prefix, e.g. ``"content"``. Distinct per WB host.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface=surface,
        token=token,
        capacity=settings.wb_catalogue_bucket_capacity,
        refill_seconds=settings.wb_catalogue_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )
