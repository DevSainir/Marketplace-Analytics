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
from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_BY_PERIOD_PATH,
    SALES_REPORTS_DETAILED_PATH,
    SALES_REPORTS_LIST_PATH,
)
from src.integrations.wildberries.rate_limit.gates import (
    NullRateGate,
    RateGate,
    TokenBucketRateGate,
)

#: Advertising endpoints WB meters far more generously than ``/adv/v3/fullstats``,
#: whose 3-per-minute budget the surface default is sized from. Source: WB's own
#: published rate-limit table.
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


#: Statistics endpoints paced on buckets of their own rather than the surface
#: default. The default was the settlement report's one request per 960 s
#: until that report left the surface on 2026-09-22; it is one a minute now,
#: and the notes below are about why each path was listed when it was not.
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

#: How long a background walk must let a token sit before it may take it.
#:
#: Several things want the report endpoint: the harvest tick, a seller
#: pressing «Обновить», and the history backfill. Without an order they simply
#: race, and the loser is whoever asked second — which on 2026-09-12 was the
#: fresh report, waiting behind history nobody needed today.
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


#: The longest a caller on this surface may queue for a token before giving up.
#:
#: It used to be ``wb_statistics_walk_queue_seconds`` — 1000 s, sized for an
#: endpoint whose refill was 960 s. Here the refill is 60 s, so a long wait is
#: not a bucket filling but WB refusing, and a caller that sleeps through a
#: refusal is worse off than one that re-enqueues against it. It also has to fit
#: inside its callers: the backfill tick's soft limit is 900 s and the harvest
#: holds a 600 s fleet lock, and overrunning a soft limit is not a slow tick but
#: a silent one — ``SoftTimeLimitExceeded`` is not the ``IntegrationError``
#: either lane catches.
#:
#: **Four minutes, not two, and the difference is whether a background caller
#: can run at all.** At two it equalled :data:`BACKGROUND_RESERVE_SECONDS`, and
#: a reserving caller waits the reserve PLUS whatever of the refill is left — so
#: the gate slept its 120 s, was told it needed 120 s more, and refused its own
#: request. Measured on NEVA 2026-09-23: «would need 240s of queueing (cap
#: 120s); not sending the request», on every tick, with nothing ever sent. The
#: forward harvest never saw it because it does not reserve.
#:
#: The invariant, pinned by a test: this must exceed the reserve plus one
#: refill, or the courtesy becomes a prohibition.
FINANCE_QUEUE_SECONDS = 240.0

#: The three Finance-surface report methods, all documented and measured at one
#: request a minute, burst 1 (2026-09-22).
#:
#: They are SEPARATE buckets, which is the whole reason discovery stops being
#: expensive: asking «is there a new report» through `sales-reports/list` no
#: longer spends the budget that fetching one through `detailed` needs. On the
#: endpoint they replaced those were the same request against the same bucket,
#: and the publication calendar (`finreports/services/publication.py`, deleted
#: 2026-09-23) existed to avoid spending it.
FINANCE_REPORT_ENDPOINT_BUCKETS: Mapping[str, tuple[int, float]] = {
    SALES_REPORTS_LIST_PATH: (1, 60.0),
    SALES_REPORTS_DETAILED_PATH: (1, 60.0),
    SALES_REPORTS_BY_PERIOD_PATH: (1, 60.0),
}


def finance_reports_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for WB's realization reports on the Finance surface.

    No `shared_block`. The statistics settlement path shares one because five
    sellers were measured holding a single countdown there on 2026-09-17 — an
    endpoint WB had already switched off. Nothing suggests this surface behaves
    that way, and sharing a block on no evidence stalls four sellers over a
    refusal that costs the fifth nothing.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's «Финансы» token — the bucket is per token, and
            WB meters per seller account, so one seller's walk never throttles
            another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="finance",
        token=token,
        # Nothing on this surface is looser than the two report methods, so the
        # default is the same figure: an endpoint we have not measured is paced
        # conservatively rather than unpaced.
        capacity=1,
        refill_seconds=60.0,
        # A page is worth waiting a minute for; the walk takes its token before
        # opening a transaction, so waiting costs wall clock and nothing else.
        # Past that it is a refusal rather than a bucket — see the constant.
        max_wait_seconds=FINANCE_QUEUE_SECONDS,
        endpoint_buckets=FINANCE_REPORT_ENDPOINT_BUCKETS,
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
    """Build the pacing gate for the statistics surface.

    ``/supplier/sales`` and ``/supplier/orders`` carry buckets of their own
    (:data:`STATISTICS_ENDPOINT_BUCKETS`); anything else takes the surface
    default of one a minute. Buckets are per token and measurably not per
    address — 2026-09-22, the documents bucket stayed empty for the same token
    from a different egress.

    No path here shares its penalty block across tokens any more. That was the
    settlement report alone (``shared_block``, measured 2026-09-17: five sellers
    holding block expiries 0.77 s apart), and it left this surface on
    2026-09-22. The mechanism stays in the gate for an endpoint that behaves
    that way again.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's statistics token — the bucket is per token, so
            one seller's calls never throttle another's.

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


def feedbacks_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the «Вопросы и отзывы» surface.

    Two callers share it: the daily review history walks ``/api/v1/feedbacks``
    page by page, and the `guide` capture reads reviews and questions monthly.
    The bucket is per token and per endpoint like every other one here.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's «Вопросы и отзывы» (or unified) token.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="feedbacks",
        token=token,
        capacity=settings.wb_feedbacks_bucket_capacity,
        refill_seconds=settings.wb_feedbacks_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )


#: The bucket "token" of the public storefront. There is no seller credential
#: there, so every workspace's reads share ONE bucket — which is the point: the
#: storefront sees one reader at our address, however many sellers it serves.
STOREFRONT_BUCKET_TOKEN = "storefront-public"  # noqa: S105 - a bucket name, not a secret


def storefront_feedbacks_rate_gate(settings: Settings) -> RateGate:
    """Build the pacing gate for the public storefront's review summary.

    One token, refilled every few seconds, shared across the whole fleet (see
    :data:`STOREFRONT_BUCKET_TOKEN`). The caller keys every request on one
    ``rate_key`` rather than on the per-card-group path, or each ``imtId`` would get
    a fresh bucket and nothing would be paced.

    Args:
        settings: Refill interval and the Redis DSN.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="storefront-feedbacks",
        token=STOREFRONT_BUCKET_TOKEN,
        capacity=1,
        refill_seconds=settings.wb_storefront_feedbacks_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )
