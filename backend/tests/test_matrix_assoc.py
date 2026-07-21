"""Unit tests for the associative-conversion breakdown (services/matrix/).

The carts/orders cells show a campaign's ALL-VARIANT total; these cover the
per-variant decomposition behind the hover. The load-bearing property is that
a cell's rows SUM to the number the cell displays — a breakdown that doesn't
add up is worse than none, since the reader checks it against the cell.
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
)
from src.modules.monitoring.repos.advertising import CampaignDaySkuTotal, CampaignDayTotal
from src.modules.monitoring.schemas.matrix import MatrixAdBucketBase
from src.modules.monitoring.services.matrix import derive_base_state

DAY = date(2026, 7, 1)
VIEWED = 100
SIBLING = 200
OTHER = 300


def _campaign(campaign_id: int, bid_type: str, *, search: bool, shelves: bool) -> Campaign:
    """An in-memory Campaign dimension row."""
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
    campaign_id: int, *, views: int, clicks: int, add_to_cart: int, orders: int
) -> AdvertisingStatDaily:
    """The viewed SKU's own campaign-day facts."""
    return AdvertisingStatDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        app_type=1,
        nm_id=VIEWED,
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        # Above _MIN_CAMPAIGN_DAY_SPEND: these fixtures exercise the associative
        # breakdown, so their campaign-days must count as real delivery.
        spend=10000.0,
        orders=orders,
        order_sum=0.0,
    )


def _search_row(
    campaign_id: int, *, views: int, clicks: int, add_to_cart: int, orders: int
) -> AdvertisingSearchStatDaily:
    """The SEARCH-zone slice of the viewed SKU's campaign-day."""
    return AdvertisingSearchStatDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        nm_id=VIEWED,
        views=views,
        clicks=clicks,
        add_to_cart=add_to_cart,
        spend=5000.0,
        orders=orders,
    )


def _derive(
    *,
    ad_rows: list[AdvertisingStatDaily],
    search_rows: list[AdvertisingSearchStatDaily],
    campaigns: dict[int, Campaign],
    totals: list[CampaignDayTotal],
    sku_totals: list[CampaignDaySkuTotal],
) -> dict[str, MatrixAdBucketBase]:
    """Derive one day's buckets."""
    base = derive_base_state(
        date_from=DAY,
        date_to=DAY,
        funnel_rows=[],
        ad_rows=ad_rows,
        search_rows=search_rows,
        campaigns=campaigns,
        campaign_totals=totals,
        campaign_sku_totals=sku_totals,
        sku_labels={VIEWED: "M-VIEWED", SIBLING: "M-SIBLING"},
        nm_id=VIEWED,
    )
    return base.days[0].buckets


def test_single_zone_campaign_breaks_down_exactly() -> None:
    """A manual shelves-only campaign needs no split — the rows are WB's own."""
    buckets = _derive(
        ad_rows=[_ad_row(1, views=1000, clicks=100, add_to_cart=56, orders=10)],
        search_rows=[],
        campaigns={1: _campaign(1, "manual", search=False, shelves=True)},
        totals=[CampaignDayTotal(campaign_id=1, stat_date=DAY, add_to_cart=57, orders=11)],
        sku_totals=[
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=VIEWED, add_to_cart=56, orders=10
            ),
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=SIBLING, add_to_cart=1, orders=1
            ),
        ],
    )
    shelves = buckets["manual_shelves"]

    assert shelves.assoc_exact is True
    assert [(s.nm_id, s.vendor_code, s.add_to_cart) for s in shelves.assoc_skus] == [
        (VIEWED, "M-VIEWED", 56),
        (SIBLING, "M-SIBLING", 1),
    ]
    # The rows add up to the number the cell shows.
    assert sum(s.add_to_cart for s in shelves.assoc_skus) == shelves.assoc_add_to_cart == 57
    assert sum(s.orders for s in shelves.assoc_skus) == shelves.assoc_orders == 11


def test_split_campaign_with_an_empty_search_zone_stays_exact() -> None:
    """A zone that took none of the extra forces the division — no estimate.

    The live shape: a unified campaign delivers almost entirely on shelves, so
    search converts nothing and every associated cart belongs to shelves.
    """
    buckets = _derive(
        ad_rows=[_ad_row(1, views=12283, clicks=386, add_to_cart=56, orders=10)],
        search_rows=[_search_row(1, views=23, clicks=1, add_to_cart=0, orders=0)],
        campaigns={1: _campaign(1, "unified", search=True, shelves=True)},
        totals=[CampaignDayTotal(campaign_id=1, stat_date=DAY, add_to_cart=57, orders=11)],
        sku_totals=[
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=VIEWED, add_to_cart=56, orders=10
            ),
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=SIBLING, add_to_cart=1, orders=1
            ),
        ],
    )
    shelves = buckets["uni_shelves"]

    assert shelves.assoc_exact is True
    assert {(s.nm_id, s.add_to_cart) for s in shelves.assoc_skus} == {(VIEWED, 56), (SIBLING, 1)}
    assert sum(s.add_to_cart for s in shelves.assoc_skus) == shelves.assoc_add_to_cart == 57
    # The search leg converted nothing of its own and took none of the extra.
    assert buckets["uni_search"].assoc_skus == []


def test_split_campaign_apportions_the_extra_and_flags_it() -> None:
    """A genuinely divided extra is apportioned — rows still sum, flag drops.

    The viewed SKU's own split stays exact (WB's normquery slice states it);
    only the associated variants are estimated across the two zones.
    """
    buckets = _derive(
        ad_rows=[_ad_row(1, views=1000, clicks=200, add_to_cart=40, orders=10)],
        # Half the viewed SKU's carts came from search -> half the extra does.
        search_rows=[_search_row(1, views=500, clicks=100, add_to_cart=20, orders=5)],
        campaigns={1: _campaign(1, "unified", search=True, shelves=True)},
        totals=[CampaignDayTotal(campaign_id=1, stat_date=DAY, add_to_cart=50, orders=14)],
        sku_totals=[
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=VIEWED, add_to_cart=40, orders=10
            ),
            CampaignDaySkuTotal(
                campaign_id=1, stat_date=DAY, nm_id=SIBLING, add_to_cart=6, orders=3
            ),
            CampaignDaySkuTotal(campaign_id=1, stat_date=DAY, nm_id=OTHER, add_to_cart=4, orders=1),
        ],
    )
    search, shelves = buckets["uni_search"], buckets["uni_shelves"]

    assert search.assoc_exact is False
    assert shelves.assoc_exact is False

    # Every leg's rows still add up to the number its cell shows.
    for bucket in (search, shelves):
        assert sum(s.add_to_cart for s in bucket.assoc_skus) == bucket.assoc_add_to_cart
        assert sum(s.orders for s in bucket.assoc_skus) == bucket.assoc_orders

    # The viewed SKU's own split is fact, not estimate: 20 of its 40 carts.
    assert next(s.add_to_cart for s in search.assoc_skus if s.nm_id == VIEWED) == 20
    assert next(s.add_to_cart for s in shelves.assoc_skus if s.nm_id == VIEWED) == 20

    # Nothing is invented or lost: each variant's legs sum to its campaign total.
    for nm_id, carts in ((SIBLING, 6), (OTHER, 4)):
        in_search = next((s.add_to_cart for s in search.assoc_skus if s.nm_id == nm_id), 0)
        in_shelves = next((s.add_to_cart for s in shelves.assoc_skus if s.nm_id == nm_id), 0)
        assert in_search + in_shelves == carts


def test_breakdown_is_absent_without_harvested_sku_totals() -> None:
    """No per-variant rows harvested (a legacy window) — totals still render."""
    buckets = _derive(
        ad_rows=[_ad_row(1, views=1000, clicks=100, add_to_cart=56, orders=10)],
        search_rows=[],
        campaigns={1: _campaign(1, "manual", search=False, shelves=True)},
        totals=[CampaignDayTotal(campaign_id=1, stat_date=DAY, add_to_cart=57, orders=11)],
        sku_totals=[],
    )
    shelves = buckets["manual_shelves"]

    assert shelves.assoc_skus == []
    assert shelves.assoc_add_to_cart == 57
