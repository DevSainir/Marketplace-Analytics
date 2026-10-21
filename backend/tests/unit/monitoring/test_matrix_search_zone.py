"""Unit tests for the «Поиск»/«Каталог» split of WB search campaigns.

A WB search campaign also delivers in the catalog zone: the normquery slice is
the «Поиск» half and the remainder is «Каталог». The split is only as sound as
its clamping — a slice reported above the campaign's own totals must not
manufacture negative catalog numbers. The figures are sample numbers.
"""

from __future__ import annotations

from tests.support.matrix_rows import DAY1, _ad_row, _campaign, _cell, _matrix, _search_row


# --------------------------------------------------------------------------- #
# «Руч. каталог»: WB search campaigns also deliver in the catalog zone —
# normquery slice = «Поиск», remainder = «Каталог» (sample numbers).
# --------------------------------------------------------------------------- #
def test_search_campaign_splits_into_search_and_catalog() -> None:
    """A search-only manual campaign splits into «Поиск» + «Каталог» zones."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [
        _ad_row(
            1,
            DAY1,
            views=14271,
            clicks=835,
            add_to_cart=128,
            spend=12407.71,
            orders=92,
            order_sum=1000,
        )
    ]
    search_rows = [
        _search_row(1, DAY1, views=12361, clicks=739, add_to_cart=114, spend=11121.31, orders=87)
    ]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    assert _cell(rows, "views", 0, "manual_search") == 12361
    assert _cell(rows, "views", 0, "manual_catalog") == 1910
    assert _cell(rows, "spend", 0, "manual_search") == 11121.31
    assert _cell(rows, "spend", 0, "manual_catalog") == 1286.4
    assert _cell(rows, "orders", 0, "manual_catalog") == 5
    # «Доля трафика» spans all manual zones (86.62 + 13.38 = 100).
    assert _cell(rows, "traffic_share", 0, "manual_search") == 86.62
    assert _cell(rows, "traffic_share", 0, "manual_catalog") == 13.38
    # Zone-attributed revenue does not exist -> both legs taint to «—».
    assert _cell(rows, "order_sum", 0, "manual_search") is None
    assert _cell(rows, "order_sum", 0, "manual_catalog") is None


def test_search_campaign_without_slice_stays_in_search() -> None:
    """No harvested normquery slice (legacy rows) -> the whole day is «Поиск»."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, spend=5000, orders=5, order_sum=50000)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows)

    assert _cell(rows, "views", 0, "manual_search") == 100
    assert _cell(rows, "views", 0, "manual_catalog") is None
    # Unpriced day (no snapshot here) -> the derived revenue has no price to
    # work from and stays blank.
    assert _cell(rows, "order_sum", 0, "manual_search") is None


def test_search_slice_clamped_to_campaign_totals() -> None:
    """Attribution drift (search > fullstats) never yields negative shelves."""
    campaigns = {1: _campaign(1, "unified", search=True, shelves=True)}
    ad_rows = [_ad_row(1, DAY1, views=10, clicks=1, spend=500)]
    search_rows = [_search_row(1, DAY1, views=12, clicks=2, spend=600)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, search_rows=search_rows)

    # Search clamps to the campaign total (10); shelves = 0 -> not a candidate.
    assert _cell(rows, "views", 0, "uni_search") == 10
    assert _cell(rows, "views", 0, "uni_shelves") is None
