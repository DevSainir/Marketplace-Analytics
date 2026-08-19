"""Shared row builders for the metrics-matrix unit tests.

The matrix builder consumes seven harvested row types at once, so a test that
constructs them all inline drowns its own assertion in setup. These builders
keep every matrix test to the shape that matters: build the rows that differ,
assert the cell.

They live in ``tests/support`` rather than in a ``conftest`` because they are
plain functions, not fixtures — a test picks the two or three it needs and
still reads top to bottom.

Consumed by ``tests/unit/monitoring/test_matrix*.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.advertising import CampaignDayTotal, CampaignSearchDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixAdSkuBase,
)
from src.modules.monitoring.services.matrix import build_metrics_matrix

DAY1 = date(2026, 7, 1)
DAY2 = date(2026, 7, 2)


def _campaign(campaign_id: int, bid_type: str, search: bool, shelves: bool) -> Campaign:
    """Construct an in-memory Campaign dimension row."""
    return Campaign(
        campaign_id=campaign_id,
        type=9,
        status=9,
        status_label="active",
        bid_type=bid_type,
        placement_search=search,
        placement_recommendations=shelves,
        name=f"campaign {campaign_id}",
        payment_type="cpm",
    )


def _ad_row(
    campaign_id: int,
    stat_date: date,
    *,
    app_type: int = 1,
    views: int = 0,
    clicks: int = 0,
    add_to_cart: int = 0,
    spend: float = 0.0,
    orders: int = 0,
    order_sum: float = 0.0,
) -> AdvertisingStatDaily:
    """Construct an in-memory advertising fact row."""
    return AdvertisingStatDaily(
        stat_date=stat_date,
        campaign_id=campaign_id,
        app_type=app_type,
        nm_id=111,
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        spend=spend,
        orders=orders,
        order_sum=order_sum,
    )


def _search_row(
    campaign_id: int,
    stat_date: date,
    *,
    views: int = 0,
    clicks: int = 0,
    add_to_cart: int = 0,
    spend: float = 0.0,
    orders: int = 0,
) -> AdvertisingSearchStatDaily:
    """Construct an in-memory search-zone fact row."""
    return AdvertisingSearchStatDaily(
        stat_date=stat_date,
        campaign_id=campaign_id,
        nm_id=111,
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        spend=spend,
        orders=orders,
    )


def _campaign_total(
    campaign_id: int,
    stat_date: date,
    *,
    add_to_cart: int = 0,
    orders: int = 0,
    views: int = 0,
    clicks: int = 0,
    spend: float = 0.0,
    order_sum: float = 0.0,
    traffic_add_to_cart: int | None = None,
    traffic_orders: int | None = None,
) -> CampaignDayTotal:
    """Construct one campaign-day's all-nm_id totals.

    ``traffic_*`` default to zero, which the base state then clamps up to the
    viewed card's own rows — the shape of a single-card campaign, where the card
    IS the campaign's traffic and the totals only add what associated variants
    converted.
    """
    return CampaignDayTotal(
        campaign_id=campaign_id,
        stat_date=stat_date,
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        spend=spend,
        orders=orders,
        order_sum=order_sum,
        traffic_add_to_cart=traffic_add_to_cart or 0,
        traffic_orders=traffic_orders or 0,
    )


def _ad_bucket(
    *,
    views: int = 0,
    clicks: int = 0,
    add_to_cart: int = 0,
    spend: float = 0.0,
    orders: int = 0,
    order_sum: float | None = 0.0,
    sku_add_to_cart: int | None = None,
    sku_orders: int | None = None,
    assoc_skus: list[AssocSkuCount] | None = None,
    assoc_exact: bool = True,
) -> MatrixAdBucketBase:
    """One ad bucket's input facts: the кампания's, with the card's share.

    The card's share of the conversions defaults to the whole — a single-card
    campaign, where the card IS the campaign — so a fixture only states
    ``sku_add_to_cart``/``sku_orders`` when it wants associated variants in
    play. Traffic and spend are always the advertised card's own.
    """
    return MatrixAdBucketBase(
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        spend=spend,
        orders=orders,
        order_sum=order_sum,
        sku=MatrixAdSkuBase(
            views=views,
            clicks=clicks,
            add_to_cart=add_to_cart if sku_add_to_cart is None else sku_add_to_cart,
            spend=spend,
            orders=orders if sku_orders is None else sku_orders,
        ),
        assoc_skus=assoc_skus or [],
        assoc_exact=assoc_exact,
    )


def _funnel_row(
    stat_date: date,
    *,
    open_count: int = 0,
    cart_count: int = 0,
    order_count: int = 0,
    buyout_count: int = 0,
    cancel_count: int | None = None,
    buyout_conversion: float = 0,
) -> SalesFunnelDaily:
    """Construct an in-memory funnel row (₽ volumes are no longer stored).

    ``cancel_count`` defaults to ``None`` — "the cohort pass has not refreshed
    this day", which is what a day outside the aggregate's refresh window looks
    like in the database.
    """
    return SalesFunnelDaily(
        stat_date=stat_date,
        nm_id=111,
        open_count=open_count,
        cart_count=cart_count,
        order_count=order_count,
        buyout_count=buyout_count,
        cancel_count=cancel_count,
        add_to_wishlist=0,
        cart_conversion=0,
        order_conversion=0,
        buyout_conversion=buyout_conversion,
    )


def _price_row(
    stat_date: date, *, seller: float | None = None, customer: float | None = None
) -> PriceSnapshot:
    """Construct an in-memory price snapshot row."""
    return PriceSnapshot(
        stat_date=stat_date, nm_id=111, seller_price=seller, customer_price=customer
    )


def _matrix(
    *,
    campaigns: dict[int, Campaign],
    ad_rows: list[AdvertisingStatDaily],
    search_rows: list[AdvertisingSearchStatDaily] | None = None,
    funnel_rows: list[SalesFunnelDaily] | None = None,
    price_snapshots: list[PriceSnapshot] | None = None,
    stock_daily: list[StockDailyTotal] | None = None,
    campaign_totals: list[CampaignDayTotal] | None = None,
    campaign_search_totals: list[CampaignSearchDayTotal] | None = None,
    date_from: date = DAY1,
    date_to: date = DAY1,
) -> dict[str, list[float | None]]:
    """Build a matrix and index its rows by metric key."""
    matrix = build_metrics_matrix(
        date_from=date_from,
        date_to=date_to,
        funnel_rows=funnel_rows or [],
        ad_rows=ad_rows,
        search_rows=search_rows or [],
        campaigns=campaigns,
        price_snapshots=price_snapshots or [],
        stock_daily=stock_daily or [],
        campaign_totals=campaign_totals,
        campaign_search_totals=campaign_search_totals,
    )
    return {row.key: row.values for row in matrix.rows}


def _cell(
    rows: dict[str, list[float | None]], key: str, day_index: int, bucket: str
) -> float | None:
    """Read one matrix cell by metric key, day index, and bucket key."""
    bucket_index = MATRIX_BUCKETS.index(bucket)
    return rows[key][day_index * len(MATRIX_BUCKETS) + bucket_index]


# --------------------------------------------------------------------------- #
# Reference scenario: two real campaigns — a unified one (shown in BOTH its WB
# search/shelves zones) and a manual search one. Plus a noise campaign, cut.
#
# Every ₽ figure here is scaled so the two real campaigns clear
# ``_MIN_CAMPAIGN_DAY_SPEND`` (a campaign-day below it is residual trickle, not
# delivery — see matrix.py) while the noise campaign stays under it. Spend,
# ad revenue and the price snapshot are scaled TOGETHER, so every ratio the
# tests assert (ДРР, СПП, «Доля трафика») is unchanged by the scaling.
# --------------------------------------------------------------------------- #
def _two_campaign_rows() -> dict[str, list[float | None]]:
    campaigns = {
        1: _campaign(1, "unified", search=True, shelves=True),
        2: _campaign(2, "manual", search=True, shelves=False),
        # Campaign 4 has no dimension row -> unclassifiable -> always cut.
    }
    ad_rows = [
        # Unified campaign (100 views total; search slice = 30 from normquery, so
        # shelves = 70). Both zones are shown; revenue taints their order_sum.
        _ad_row(
            1,
            DAY1,
            app_type=1,
            views=60,
            clicks=6,
            add_to_cart=3,
            spend=3000,
            orders=1,
            order_sum=60000,
        ),
        _ad_row(
            1,
            DAY1,
            app_type=32,
            views=40,
            clicks=4,
            add_to_cart=2,
            spend=2000,
            orders=1,
            order_sum=40000,
        ),
        # Manual search campaign (40 views = 40% of the leader -> kept).
        _ad_row(2, DAY1, views=40, clicks=4, add_to_cart=2, spend=2000, orders=1, order_sum=50000),
        # Unclassifiable noise campaign: excluded entirely.
        _ad_row(4, DAY1, views=10, clicks=1, spend=5),
    ]
    search_rows = [_search_row(1, DAY1, views=30, clicks=3, add_to_cart=1, spend=1500, orders=1)]
    funnel_rows = [
        _funnel_row(DAY1, open_count=200, cart_count=20, order_count=10, buyout_count=6),
        # Matured cohort inside the lagged window: 4 buyouts + 6 refusals = 10
        # decided deliveries -> 40%.
        _funnel_row(DAY1 - timedelta(days=10), order_count=8, buyout_count=4, cancel_count=6),
    ]
    price_snapshots = [_price_row(DAY1, seller=50000, customer=35000)]
    return _matrix(
        campaigns=campaigns,
        ad_rows=ad_rows,
        search_rows=search_rows,
        funnel_rows=funnel_rows,
        price_snapshots=price_snapshots,
        date_to=DAY2,
    )
