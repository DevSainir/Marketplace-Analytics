"""Unit tests for the campaign id each advertising cell carries (services/matrix/).

The matrix header links a traffic group to the WB campaign behind it, so every
ad bucket has to name that campaign — every zone of a split campaign, and each
of two campaigns kept on one day under its own buckets.
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
)
from src.modules.monitoring.schemas.matrix import MatrixAdBucketBase
from src.modules.monitoring.services.matrix import derive_base_state

DAY = date(2026, 9, 25)
VIEWED = 953770957
UNIFIED = 97455860
MANUAL = 97455887


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


def _ad_row(campaign_id: int, *, views: int) -> AdvertisingStatDaily:
    """The viewed card's campaign-day, spending well above the delivery floor."""
    return AdvertisingStatDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        app_type=1,
        nm_id=VIEWED,
        views=views,
        clicks=views // 50,
        add_to_cart=5,
        spend=5000.0,
        orders=2,
        order_sum=0.0,
    )


def _search_row(campaign_id: int, *, views: int) -> AdvertisingSearchStatDaily:
    """The search-zone slice of the viewed card's campaign-day."""
    return AdvertisingSearchStatDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        nm_id=VIEWED,
        views=views,
        clicks=views // 50,
        add_to_cart=2,
        spend=2000.0,
        orders=1,
    )


def _buckets(
    ad_rows: list[AdvertisingStatDaily],
    search_rows: list[AdvertisingSearchStatDaily],
    campaigns: dict[int, Campaign],
) -> dict[str, MatrixAdBucketBase]:
    """Derive the one day's buckets, with no campaign-grain totals (stand-in path)."""
    base = derive_base_state(
        date_from=DAY,
        date_to=DAY,
        funnel_rows=[],
        ad_rows=ad_rows,
        search_rows=search_rows,
        campaigns=campaigns,
        nm_id=VIEWED,
    )
    return base.days[0].buckets


def test_every_zone_of_a_split_campaign_names_it() -> None:
    buckets = _buckets(
        [_ad_row(UNIFIED, views=14000)],
        [_search_row(UNIFIED, views=6000)],
        {UNIFIED: _campaign(UNIFIED, "unified", search=True, shelves=True)},
    )

    assert {key: b.campaign_id for key, b in buckets.items()} == {
        "uni_search": UNIFIED,
        "uni_shelves": UNIFIED,
    }


def test_two_kept_campaigns_each_name_their_own_buckets() -> None:
    buckets = _buckets(
        [_ad_row(UNIFIED, views=14000), _ad_row(MANUAL, views=12000)],
        [_search_row(UNIFIED, views=6000), _search_row(MANUAL, views=11000)],
        {
            UNIFIED: _campaign(UNIFIED, "unified", search=True, shelves=True),
            MANUAL: _campaign(MANUAL, "manual", search=True, shelves=False),
        },
    )

    assert buckets["uni_search"].campaign_id == UNIFIED
    assert buckets["uni_shelves"].campaign_id == UNIFIED
    assert buckets["manual_search"].campaign_id == MANUAL
    assert buckets["manual_catalog"].campaign_id == MANUAL
