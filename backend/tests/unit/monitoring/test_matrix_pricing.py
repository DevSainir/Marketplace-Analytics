"""Unit tests for the price- and stock-derived cells of the metrics matrix.

Order/buyout roubles are DERIVED (count x seller price) rather than summed from
WB, and "WB discount" is the gap between the seller and customer prices. Both therefore
hinge on a price snapshot existing for that exact day — so the cases that
matter are the ones where it does not, or where it belongs to another day.
Stock rows are the same shape of problem: they exist only on days a snapshot
was actually taken.
"""

from __future__ import annotations

from src.modules.monitoring.models import Campaign
from src.modules.monitoring.repos.stocks import StockDailyTotal
from tests.support.matrix_rows import (
    DAY1,
    DAY2,
    _ad_row,
    _campaign,
    _cell,
    _funnel_row,
    _matrix,
    _price_row,
    _two_campaign_rows,
)


def test_total_volumes_and_spp_derive_from_seller_price() -> None:
    """The "Orders, ₽" = count x price; "Buyouts, ₽" = "Orders, ₽" x "Buyout rate"."""
    rows = _two_campaign_rows()

    # DAY1: order_count 10 x 50000 = 500000; buyout% = 40% (matured cohort) →
    # "Buyouts, ₽" = 500000 x 0.40 = 200000 (order-date, congruent with "Orders, ₽").
    assert _cell(rows, "order_sum", 0, "total") == 500000.0
    assert _cell(rows, "buyout_percent", 0, "total") == 40.0
    assert _cell(rows, "buyout_sum", 0, "total") == 200000.0
    assert _cell(rows, "seller_price", 0, "total") == 50000.0
    assert _cell(rows, "customer_price", 0, "total") == 35000.0
    assert _cell(rows, "spp", 0, "total") == 30.0  # (50000-35000)/50000 x 100
    # DRR over the derived ₽: spend 7000 / 500000 and / 200000.
    assert _cell(rows, "drr_orders", 0, "total") == 1.4
    assert _cell(rows, "drr_sales", 0, "total") == 3.5
    # Prices/SPP are "Overall"-only (never on ad buckets or "Organic").
    for bucket in ("uni_search", "manual_search", "organic"):
        assert _cell(rows, "seller_price", 0, bucket) is None
        assert _cell(rows, "spp", 0, bucket) is None


def test_unpriced_day_leaves_volumes_and_spp_empty() -> None:
    """With no price snapshot, "Orders/Buyouts, ₽" and "WB discount" render "—"."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, spend=50, orders=5)]
    funnel_rows = [_funnel_row(DAY1, open_count=100, order_count=6, buyout_count=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, funnel_rows=funnel_rows)

    assert _cell(rows, "order_sum", 0, "total") is None
    assert _cell(rows, "buyout_sum", 0, "total") is None
    assert _cell(rows, "seller_price", 0, "total") is None
    assert _cell(rows, "spp", 0, "total") is None


def test_price_only_day_shows_prices_but_no_counts() -> None:
    """The CURRENT day: prices are snapshotted at harvest, the funnel lags a day.

    Prices and SPP must render; the count cells (and everything derived from
    them — "Orders, ₽", "Organic") must stay blank, because zero counts on a
    not-yet-served day are not facts.
    """
    funnel_rows = [_funnel_row(DAY1, open_count=100, cart_count=10, order_count=5)]
    price_snapshots = [
        _price_row(DAY1, seller=100, customer=80),
        _price_row(DAY2, seller=110, customer=90),  # DAY2 has NO funnel row
    ]

    rows = _matrix(
        campaigns={},
        ad_rows=[],
        funnel_rows=funnel_rows,
        price_snapshots=price_snapshots,
        date_to=DAY2,
    )

    # DAY2: prices/SPP show…
    assert _cell(rows, "seller_price", 1, "total") == 110.0
    assert _cell(rows, "customer_price", 1, "total") == 90.0
    assert _cell(rows, "spp", 1, "total") == 18.18  # (110-90)/110 x 100
    # …while counts and their derivatives stay blank (0 would be fabricated).
    for key in ("clicks", "carts", "orders", "order_sum", "cart_conversion"):
        assert _cell(rows, key, 1, "total") is None
    assert _cell(rows, "clicks", 1, "organic") is None
    # DAY1 (real funnel row) is untouched.
    assert _cell(rows, "clicks", 0, "total") == 100
    assert _cell(rows, "order_sum", 0, "total") == 500.0


def test_price_applies_only_to_its_snapshot_day() -> None:
    """A day without its own snapshot stays unpriced — no carry-forward."""
    campaigns: dict[int, Campaign] = {}
    funnel_rows = [
        _funnel_row(DAY1, order_count=2),
        _funnel_row(DAY2, order_count=3),
    ]
    # Only DAY1 has a snapshot; DAY2 was never observed and must render "—".
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
    """Stock rows live in "Overall" only and only on actual snapshot days."""
    campaigns: dict[int, Campaign] = {}
    funnel_rows = [_funnel_row(DAY1, order_count=1), _funnel_row(DAY2, order_count=1)]
    # Only DAY1 has a snapshot; DAY2 was never observed and must render "—".
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
    # Total = quantity + both in-transit legs, derived server-side.
    assert _cell(rows, "stock_total", 0, "total") == 49.0
    for key in ("stock_quantity", "stock_to_client", "stock_from_client", "stock_total"):
        assert _cell(rows, key, 1, "total") is None
    # Stock is "Overall"-only; ad buckets and "Organic" stay empty.
    for bucket in ("uni_search", "manual_search", "organic"):
        assert _cell(rows, "stock_quantity", 0, bucket) is None
        assert _cell(rows, "stock_total", 0, bucket) is None


def test_stock_rows_empty_without_snapshots() -> None:
    """A SKU with no stock snapshots renders "—" in the stock rows."""
    funnel_rows = [_funnel_row(DAY1, order_count=1)]

    rows = _matrix(campaigns={}, ad_rows=[], funnel_rows=funnel_rows)

    assert _cell(rows, "stock_quantity", 0, "total") is None
    assert _cell(rows, "stock_to_client", 0, "total") is None
    assert _cell(rows, "stock_total", 0, "total") is None
