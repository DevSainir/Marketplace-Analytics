"""Unit tests for dominant-campaign selection in the metrics matrix.

The matrix shows at most two campaigns per day, so *which* two it picks is the
decision every number downstream inherits. These pin the cut: a campaign-day
that is residual trickle rather than real delivery is excluded, a genuinely
significant second zone is kept, and a single dominant campaign takes the whole
share instead of being normalized against noise.
"""

from __future__ import annotations

from tests.support.matrix_rows import (
    DAY1,
    DAY2,
    _ad_row,
    _campaign,
    _cell,
    _funnel_row,
    _matrix,
    _search_row,
)


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
        _ad_row(1, DAY1, views=100, clicks=10, spend=5000, orders=5),
        _ad_row(2, DAY1, views=40, clicks=5, spend=2000, orders=2),  # 40% of leader
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


def test_trickling_campaign_day_is_cut() -> None:
    """A campaign-day spending a few ₽ is trickle, not delivery, and is cut.

    The pattern: a campaign that genuinely delivers on most days spends
    3-16 ₽/day for a week — a handful of impressions and no clicks. The day
    must read «—», not present the SKU as advertised. The cut is per DAY, so
    the same campaign's delivering days are unaffected (see the DAY2 column).
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [
        # DAY1: the trickle — the exact shape complained about.
        _ad_row(1, DAY1, views=75, clicks=0, add_to_cart=1, spend=16.20, orders=1),
        # DAY2: the same campaign genuinely running.
        _ad_row(1, DAY2, views=16326, clicks=955, add_to_cart=120, spend=4189, orders=36),
    ]
    funnel_rows = [_funnel_row(DAY1, open_count=100, cart_count=10, order_count=6)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, funnel_rows=funnel_rows, date_to=DAY2)

    # DAY1: cut entirely — and its 75 views do not leak into «Общая».
    assert _cell(rows, "views", 0, "manual_search") is None
    assert _cell(rows, "spend", 0, "manual_search") is None
    assert _cell(rows, "views", 0, "total") is None
    # …so that day's traffic is all organic.
    assert _cell(rows, "clicks", 0, "organic") == 100
    # DAY2: the same campaign, actually delivering -> shown.
    assert _cell(rows, "views", 1, "manual_search") == 16326
    assert _cell(rows, "spend", 1, "manual_search") == 4189
