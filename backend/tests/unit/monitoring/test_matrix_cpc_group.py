"""Unit tests for the «CPC» traffic group — pay-per-click campaigns.

WB bills these campaigns per CLICK rather than per 1000 impressions, so their
bid, their CPM and their «Доля трафика» are not readable against a CPM
campaign's. They get their own traffic-type group with the same two
display zones, and the classification that puts them there keys off the
campaign dimension's ``payment_type``, never its bid type.
"""

from __future__ import annotations

from tests.support.matrix_rows import DAY1, _ad_row, _campaign, _cell, _matrix, _search_row


def test_a_cpc_campaign_lands_in_the_cpc_group_not_the_bid_type_one() -> None:
    """A CPC campaign's zones are «CPC», never «Единая ставка».

    Its bid type still reads ``unified``, which before the CPC group put it in
    the «Единая ставка» columns — mixing a per-click bid into a per-impression
    column, where every CPM and «Доля трафика» beside it became unreadable.
    """
    campaigns = {1: _campaign(1, "unified", search=True, shelves=True, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=1000, clicks=100, spend=1200, orders=4)]
    search_rows = [_search_row(1, DAY1, views=700, clicks=80, spend=900, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    assert _cell(rows, "views", 0, "cpc_search") == 700
    assert _cell(rows, "views", 0, "cpc_shelves") == 300
    assert _cell(rows, "views", 0, "uni_search") is None
    assert _cell(rows, "views", 0, "uni_shelves") is None


def test_the_cpc_columns_carry_their_own_cost_per_click() -> None:
    """Each CPC zone's «CPC, ₽» is that zone's own spend over its own clicks.

    The whole point of the group: 900/80 in «Поиск» and 300/20 in «Полки» are
    two different bids, and a blended 12 ₽ over the campaign hides which zone
    the money went to.
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=True, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=1000, clicks=100, spend=1200, orders=4)]
    search_rows = [_search_row(1, DAY1, views=700, clicks=80, spend=900, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    assert _cell(rows, "spend", 0, "cpc_search") == 900
    assert _cell(rows, "spend", 0, "cpc_shelves") == 300
    assert _cell(rows, "cpc", 0, "cpc_search") == 11.25
    assert _cell(rows, "cpc", 0, "cpc_shelves") == 15.0


def test_a_search_only_cpc_campaign_keeps_its_whole_day_in_the_search_zone() -> None:
    """No catalog remainder is shed — the CPC group has no «Каталог» column.

    «Руч. поиск» splits its fullstats-minus-normquery remainder into «Руч.
    каталог»; doing that here would drop the leg on the floor and understate
    «Общая», which is built by summing the buckets.
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=1000, clicks=100, spend=1200, orders=4)]
    search_rows = [_search_row(1, DAY1, views=700, clicks=80, spend=900, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    assert _cell(rows, "views", 0, "cpc_search") == 1000
    assert _cell(rows, "spend", 0, "cpc_search") == 1200
    assert _cell(rows, "views", 0, "cpc_shelves") is None
    assert _cell(rows, "views", 0, "manual_catalog") is None


def test_a_shelves_only_cpc_campaign_lands_in_the_shelves_zone() -> None:
    """A CPC campaign bidding only on recommendations is «CPC · Полки»."""
    campaigns = {1: _campaign(1, "manual", search=False, shelves=True, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=1000, clicks=100, spend=1200, orders=4)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)

    assert _cell(rows, "views", 0, "cpc_shelves") == 1000
    assert _cell(rows, "views", 0, "cpc_search") is None
    assert _cell(rows, "views", 0, "manual_shelves") is None


def test_traffic_share_normalizes_within_the_cpc_group() -> None:
    """Each traffic type sums to 100% on its own — CPC included.

    A CPC campaign running beside a CPM one must not dilute the CPM columns'
    shares (nor be diluted by them): impressions bought per click and
    impressions bought per mille are not fractions of one pool.
    """
    campaigns = {
        1: _campaign(1, "unified", search=True, shelves=True),
        2: _campaign(2, "manual", search=True, shelves=True, payment_type="cpc"),
    }
    ad_rows = [
        _ad_row(1, DAY1, views=1000, clicks=50, spend=1500, orders=3),
        _ad_row(2, DAY1, views=800, clicks=90, spend=1100, orders=4),
    ]
    search_rows = [
        _search_row(1, DAY1, views=600, clicks=30, spend=900, orders=2),
        _search_row(2, DAY1, views=200, clicks=20, spend=300, orders=1),
    ]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    assert _cell(rows, "traffic_share", 0, "uni_search") == 60.0
    assert _cell(rows, "traffic_share", 0, "uni_shelves") == 40.0
    assert _cell(rows, "traffic_share", 0, "cpc_search") == 25.0
    assert _cell(rows, "traffic_share", 0, "cpc_shelves") == 75.0


def test_a_cpc_campaign_delivers_below_the_cpm_floor() -> None:
    """A CPC campaign-day clearing 50 ₽ counts as delivering, not as trickle.

    The 200 ₽ floor is calibrated on CPM economics (WB's CPM floor puts it at
    roughly 700-1300 impressions). A pay-per-click campaign buys the same delivery
    for about a quarter of that, so the CPM floor read a real delivering day as
    noise. Example: a campaign serves 646 impressions and 74 clicks for
    166.50 ₽ on one card, and the «CPC» column stayed blank on that card.
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=1154, clicks=74, spend=166.50, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)

    assert _cell(rows, "views", 0, "cpc_search") == 1154
    assert _cell(rows, "spend", 0, "cpc_search") == 166.50
    assert _cell(rows, "cpc", 0, "cpc_search") == 2.25


def test_a_cpc_campaign_that_never_delivered_is_still_cut() -> None:
    """The lower floor is not "no floor" — a no-click CPC day is still trickle.

    A paused-but-not-finished CPC campaign trickles a handful of impressions for
    0 ₽, always at 0 clicks; those must not
    open a «CPC» column that claims the card had pay-per-click traffic.
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False, payment_type="cpc")}
    ad_rows = [_ad_row(1, DAY1, views=19, clicks=0, spend=0.0)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)

    assert _cell(rows, "views", 0, "cpc_search") is None


def test_the_cpm_floor_is_unchanged_by_the_cpc_one() -> None:
    """A CPM campaign at 166.50 ₽ is still trickle — the relief is CPC-only."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=1154, clicks=74, spend=166.50, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)

    assert _cell(rows, "views", 0, "manual_search") is None
