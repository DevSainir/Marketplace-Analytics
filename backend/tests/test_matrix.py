"""Unit tests for the pure metrics-matrix builder (services/matrix.py).

Covers the load-bearing rules: the significant-campaign selection (cut noise, at
most two campaigns, a unified campaign shown in both its WB zones), «Доля
трафика» normalized within each bid type, the unified search/shelves split (with
clamping and the revenue taint), the funnel-backed «Общая»/«Органика» columns
computed over the survivors only, and the lagged «Процент выкупа» window.
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
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import MATRIX_BUCKETS
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


def _funnel_row(
    stat_date: date,
    *,
    open_count: int = 0,
    cart_count: int = 0,
    order_count: int = 0,
    buyout_count: int = 0,
) -> SalesFunnelDaily:
    """Construct an in-memory funnel row (₽ volumes are no longer stored)."""
    return SalesFunnelDaily(
        stat_date=stat_date,
        nm_id=111,
        open_count=open_count,
        cart_count=cart_count,
        order_count=order_count,
        buyout_count=buyout_count,
        add_to_wishlist=0,
        cart_conversion=0,
        order_conversion=0,
        buyout_conversion=0,
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
            spend=30,
            orders=1,
            order_sum=600,
        ),
        _ad_row(
            1,
            DAY1,
            app_type=32,
            views=40,
            clicks=4,
            add_to_cart=2,
            spend=20,
            orders=1,
            order_sum=400,
        ),
        # Manual search campaign (40 views = 40% of the leader -> kept).
        _ad_row(2, DAY1, views=40, clicks=4, add_to_cart=2, spend=20, orders=1, order_sum=500),
        # Unclassifiable noise campaign: excluded entirely.
        _ad_row(4, DAY1, views=10, clicks=1, spend=5),
    ]
    search_rows = [_search_row(1, DAY1, views=30, clicks=3, add_to_cart=1, spend=15, orders=1)]
    funnel_rows = [
        _funnel_row(DAY1, open_count=200, cart_count=20, order_count=10, buyout_count=6),
        _funnel_row(DAY1 - timedelta(days=10), order_count=8, buyout_count=4),
    ]
    price_snapshots = [_price_row(DAY1, seller=500, customer=350)]
    return _matrix(
        campaigns=campaigns,
        ad_rows=ad_rows,
        search_rows=search_rows,
        funnel_rows=funnel_rows,
        price_snapshots=price_snapshots,
        date_to=DAY2,
    )


def test_unified_shows_both_zones_and_manual_is_kept() -> None:
    """A surviving unified campaign keeps both WB zones; the manual one shows too."""
    rows = _two_campaign_rows()
    assert _cell(rows, "views", 0, "uni_search") == 30  # unified search slice shown
    assert _cell(rows, "views", 0, "uni_shelves") == 70
    assert _cell(rows, "views", 0, "manual_search") == 40
    assert _cell(rows, "views", 0, "manual_shelves") is None  # no such campaign


def test_traffic_share_normalized_within_bid_type() -> None:
    """«Доля трафика» sums to 100% within Единая and within Ручной separately."""
    rows = _two_campaign_rows()
    # Единая: 30 + 70 = 100 views -> 30% / 70%.
    assert _cell(rows, "traffic_share", 0, "uni_search") == 30.0
    assert _cell(rows, "traffic_share", 0, "uni_shelves") == 70.0
    # Ручной: the single manual campaign is 100% of its own type.
    assert _cell(rows, "traffic_share", 0, "manual_search") == 100.0


def test_split_revenue_is_tainted_not_guessed() -> None:
    """A split (unified) campaign's zone order revenue is «—»."""
    rows = _two_campaign_rows()
    assert _cell(rows, "order_sum", 0, "uni_search") is None
    assert _cell(rows, "order_sum", 0, "uni_shelves") is None
    # The single-zone manual campaign keeps its real revenue.
    assert _cell(rows, "order_sum", 0, "manual_search") == 500
    assert _cell(rows, "drr_orders", 0, "manual_search") == 4.0  # 20 / 500


def test_total_and_organic_use_survivors_only() -> None:
    """«Общая»/«Органика» count only the surviving campaigns (noise excluded)."""
    rows = _two_campaign_rows()
    # Ad roll-up = both survivors: 100 (unified) + 40 (manual) = 140 views, 70₽
    # spend, 14 clicks. The unclassifiable noise (10 views / 5₽) is NOT counted.
    assert _cell(rows, "views", 0, "total") == 140
    assert _cell(rows, "spend", 0, "total") == 70
    assert _cell(rows, "clicks", 0, "total") == 200  # funnel card opens
    # Organic = funnel - surviving ad. Ad clicks = 14 -> organic 200-14 = 186.
    assert _cell(rows, "clicks", 0, "organic") == 186
    assert _cell(rows, "carts", 0, "organic") == 13  # 20 - (3+2+2)
    assert _cell(rows, "orders", 0, "organic") == 7  # 10 - (1+1+1)


def test_catalog_column_stays_empty() -> None:
    """The legacy «Каталог» zone no longer exists in the v2 API."""
    rows = _two_campaign_rows()
    for key in rows:
        assert _cell(rows, key, 0, "uni_catalog") is None


def test_buyout_percent_uses_lagged_window() -> None:
    """«Процент выкупа» for day D reads funnel [D-21, D-7], not D itself."""
    rows = _two_campaign_rows()
    assert _cell(rows, "buyout_percent", 0, "total") == 50.0  # 4 buyouts / 8 orders
    assert _cell(rows, "buyout_percent", 1, "total") == 50.0
    assert _cell(rows, "buyout_percent", 0, "manual_search") is None


def test_day_without_any_data_renders_empty() -> None:
    """A day with no funnel and no ads yields None across ad/total/organic."""
    rows = _two_campaign_rows()
    for bucket in ("uni_search", "manual_search", "uni_shelves", "total", "organic"):
        assert _cell(rows, "views", 1, bucket) is None
        assert _cell(rows, "clicks", 1, bucket) is None


# --------------------------------------------------------------------------- #
# Dominant-campaign selection edge cases
# --------------------------------------------------------------------------- #
def test_single_dominant_campaign_gets_100_percent() -> None:
    """One dominant campaign + a negligible second zone -> only the leader, 100%.

    Mirrors SKU 995716075: a manual search campaign carries ~99.8% of the views;
    a unified campaign's tiny shelves slice (0.2%) and pure-attribution noise are
    all cut.
    """
    campaigns = {
        1: _campaign(1, "manual", search=True, shelves=False),
        2: _campaign(2, "unified", search=True, shelves=True),
        3: _campaign(3, "manual", search=True, shelves=False),
    }
    ad_rows = [
        _ad_row(1, DAY1, views=57777, clicks=3658, add_to_cart=552, spend=35034, orders=312),
        # Unified: all 124 views are shelves (search slice = 0) -> 0.2% of total.
        _ad_row(2, DAY1, views=124, clicks=3, add_to_cart=0, spend=49, orders=3),
        # Attribution-only noise: real orders but zero delivery -> never a winner.
        _ad_row(3, DAY1, views=0, clicks=0, add_to_cart=131, spend=0, orders=71),
    ]
    search_rows = [_search_row(2, DAY1, views=0, clicks=0, spend=0)]
    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)
    # Only the dominant manual search campaign survives, at 100% share.
    assert _cell(rows, "views", 0, "manual_search") == 57777
    assert _cell(rows, "traffic_share", 0, "manual_search") == 100.0
    for bucket in ("uni_search", "uni_shelves", "manual_shelves"):
        assert _cell(rows, "views", 0, bucket) is None
    # «Общая» reflects only the survivor.
    assert _cell(rows, "views", 0, "total") == 57777
    assert _cell(rows, "spend", 0, "total") == 35034


def test_significant_second_zone_is_kept() -> None:
    """A genuine second zone (≥20% of the leader's views) survives."""
    campaigns = {
        1: _campaign(1, "manual", search=True, shelves=False),
        2: _campaign(2, "manual", search=False, shelves=True),
    }
    ad_rows = [
        _ad_row(1, DAY1, views=100, clicks=10, spend=50, orders=5),
        _ad_row(2, DAY1, views=40, clicks=5, spend=20, orders=2),  # 40% of leader
    ]
    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)
    assert _cell(rows, "views", 0, "manual_search") == 100
    assert _cell(rows, "views", 0, "manual_shelves") == 40
    assert _cell(rows, "traffic_share", 0, "manual_search") == 71.43  # 100/140
    assert _cell(rows, "traffic_share", 0, "manual_shelves") == 28.57


def test_zero_delivery_campaign_is_cut() -> None:
    """A campaign with attribution orders but no real delivery shows nothing."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=0, clicks=0, add_to_cart=5, spend=0, orders=9)]
    funnel_rows = [_funnel_row(DAY1, open_count=100, cart_count=10, order_count=6)]
    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, funnel_rows=funnel_rows)
    assert _cell(rows, "views", 0, "manual_search") is None
    assert _cell(rows, "views", 0, "total") is None  # no significant ads
    # With no surviving ads, all funnel traffic is organic.
    assert _cell(rows, "clicks", 0, "organic") == 100


def test_total_volumes_and_spp_derive_from_seller_price() -> None:
    """«Заказы/Выкупы ₽» = count x seller_price; «СПП» = (seller-customer)/seller."""
    rows = _two_campaign_rows()
    # DAY1: order_count 10 x 500 = 5000; buyout_count 6 x 500 = 3000.
    assert _cell(rows, "order_sum", 0, "total") == 5000.0
    assert _cell(rows, "buyout_sum", 0, "total") == 3000.0
    assert _cell(rows, "seller_price", 0, "total") == 500.0
    assert _cell(rows, "customer_price", 0, "total") == 350.0
    assert _cell(rows, "spp", 0, "total") == 30.0  # (500-350)/500 x 100
    # DRR over the derived ₽: spend 70 / 5000 and / 3000.
    assert _cell(rows, "drr_orders", 0, "total") == 1.4
    assert _cell(rows, "drr_sales", 0, "total") == 2.33
    # Prices/СПП are «Общая»-only (never on ad buckets or «Органика»).
    for bucket in ("uni_search", "manual_search", "organic"):
        assert _cell(rows, "seller_price", 0, bucket) is None
        assert _cell(rows, "spp", 0, bucket) is None


def test_unpriced_day_leaves_volumes_and_spp_empty() -> None:
    """With no price snapshot, «Заказы/Выкупы ₽» and «СПП» render «—»."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, spend=50, orders=5)]
    funnel_rows = [_funnel_row(DAY1, open_count=100, order_count=6, buyout_count=3)]
    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, funnel_rows=funnel_rows)
    assert _cell(rows, "order_sum", 0, "total") is None
    assert _cell(rows, "buyout_sum", 0, "total") is None
    assert _cell(rows, "seller_price", 0, "total") is None
    assert _cell(rows, "spp", 0, "total") is None


def test_price_applies_only_to_its_snapshot_day() -> None:
    """A day without its own snapshot stays unpriced — no carry-forward."""
    campaigns: dict[int, Campaign] = {}
    funnel_rows = [
        _funnel_row(DAY1, order_count=2),
        _funnel_row(DAY2, order_count=3),
    ]
    # Only DAY1 has a snapshot; DAY2 was never observed and must render «—».
    price_snapshots = [_price_row(DAY1, seller=100, customer=80)]
    rows = _matrix(
        campaigns=campaigns,
        ad_rows=[],
        funnel_rows=funnel_rows,
        price_snapshots=price_snapshots,
        date_to=DAY2,
    )
    assert _cell(rows, "order_sum", 0, "total") == 200.0  # 2 x 100
    assert _cell(rows, "seller_price", 0, "total") == 100.0
    assert _cell(rows, "spp", 0, "total") == 20.0
    # The unobserved day: prices and the price-derived volumes are all empty.
    assert _cell(rows, "order_sum", 1, "total") is None
    assert _cell(rows, "seller_price", 1, "total") is None
    assert _cell(rows, "spp", 1, "total") is None


def test_stock_rows_show_in_total_on_snapshot_days_only() -> None:
    """Stock rows live in «Общая» only and only on actual snapshot days."""
    campaigns: dict[int, Campaign] = {}
    funnel_rows = [_funnel_row(DAY1, order_count=1), _funnel_row(DAY2, order_count=1)]
    # Only DAY1 has a snapshot; DAY2 was never observed and must render «—».
    stock_daily = [
        StockDailyTotal(stat_date=DAY1, quantity=42, in_way_to_client=5, in_way_from_client=2)
    ]
    rows = _matrix(
        campaigns=campaigns,
        ad_rows=[],
        funnel_rows=funnel_rows,
        stock_daily=stock_daily,
        date_to=DAY2,
    )
    assert _cell(rows, "stock_quantity", 0, "total") == 42.0
    assert _cell(rows, "stock_to_client", 0, "total") == 5.0
    assert _cell(rows, "stock_from_client", 0, "total") == 2.0
    for key in ("stock_quantity", "stock_to_client", "stock_from_client"):
        assert _cell(rows, key, 1, "total") is None
    # Stock is «Общая»-only; ad buckets and «Органика» stay empty.
    for bucket in ("uni_search", "manual_search", "organic"):
        assert _cell(rows, "stock_quantity", 0, bucket) is None


def test_stock_rows_empty_without_snapshots() -> None:
    """A SKU with no stock snapshots renders «—» in the stock rows."""
    funnel_rows = [_funnel_row(DAY1, order_count=1)]
    rows = _matrix(campaigns={}, ad_rows=[], funnel_rows=funnel_rows)
    assert _cell(rows, "stock_quantity", 0, "total") is None
    assert _cell(rows, "stock_to_client", 0, "total") is None


def test_search_slice_clamped_to_campaign_totals() -> None:
    """Attribution drift (search > fullstats) never yields negative shelves."""
    campaigns = {1: _campaign(1, "unified", search=True, shelves=True)}
    ad_rows = [_ad_row(1, DAY1, views=10, clicks=1, spend=5)]
    search_rows = [_search_row(1, DAY1, views=12, clicks=2, spend=6)]
    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)
    # Search clamps to the campaign total (10); shelves = 0 -> not a candidate.
    assert _cell(rows, "views", 0, "uni_search") == 10
    assert _cell(rows, "views", 0, "uni_shelves") is None
