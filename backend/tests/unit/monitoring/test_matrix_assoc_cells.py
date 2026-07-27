"""Unit tests for the associative-conversion cells of the BUILT metrics matrix.

The sibling ``test_matrix_assoc.py`` covers the decomposition itself — how
``derive_base_state`` apportions a campaign's all-variant totals across the
SKUs behind them. This module covers what survives into the rendered table:
when the «100(71)» decoration appears on a carts/orders cell, when it is split
across a campaign's two zones, and when it is suppressed because there is no
gap between the SKU's own number and the campaign's.
"""

from __future__ import annotations

from src.modules.monitoring.repos.advertising import CampaignDayTotal
from tests.support.matrix_rows import DAY1, _ad_row, _campaign, _cell, _matrix, _search_row


# --------------------------------------------------------------------------- #
# Associative conversions («100(71)»): campaign-level all-variant totals
# decorating the SKU's own carts/orders cells.
# --------------------------------------------------------------------------- #
def test_assoc_totals_shown_on_single_zone_campaign() -> None:
    """A single-zone campaign carries its all-variant totals exactly."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=71, spend=5000, orders=30)]
    campaign_totals = [CampaignDayTotal(campaign_id=1, stat_date=DAY1, add_to_cart=100, orders=48)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, campaign_totals=campaign_totals)

    # The SKU's own counts stay the cells' primary facts…
    assert _cell(rows, "carts", 0, "manual_search") == 71
    assert _cell(rows, "orders", 0, "manual_search") == 30
    # …decorated with the campaign totals including associated variants.
    assert _cell(rows, "carts_assoc", 0, "manual_search") == 100
    assert _cell(rows, "orders_assoc", 0, "manual_search") == 48
    # The associative rows never leak into «Общая»/«Органика».
    assert _cell(rows, "carts_assoc", 0, "total") is None
    assert _cell(rows, "carts_assoc", 0, "organic") is None


def test_assoc_extra_split_by_sku_zone_share() -> None:
    """A split campaign apportions the associative extra by the SKU's own split."""
    campaigns = {1: _campaign(1, "unified", search=True, shelves=True)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=10, spend=5000, orders=5)]
    search_rows = [_search_row(1, DAY1, views=30, clicks=3, add_to_cart=4, spend=1500, orders=2)]
    campaign_totals = [CampaignDayTotal(campaign_id=1, stat_date=DAY1, add_to_cart=20, orders=9)]

    rows = _matrix(
        campaigns=campaigns,
        ad_rows=ad_rows,
        search_rows=search_rows,
        campaign_totals=campaign_totals,
    )

    # Carts: extra 10 splits 4/10 -> search +4, shelves +6.
    assert _cell(rows, "carts", 0, "uni_search") == 4
    assert _cell(rows, "carts_assoc", 0, "uni_search") == 8
    assert _cell(rows, "carts", 0, "uni_shelves") == 6
    assert _cell(rows, "carts_assoc", 0, "uni_shelves") == 12
    # Orders: extra 4 splits 2/5 -> search +2, shelves +2; leg sums stay exact.
    assert _cell(rows, "orders_assoc", 0, "uni_search") == 4
    assert _cell(rows, "orders_assoc", 0, "uni_shelves") == 5


def test_assoc_hidden_without_a_gap() -> None:
    """No associated-variant conversions -> the assoc rows stay «—»."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=7, spend=5000, orders=3)]
    campaign_totals = [CampaignDayTotal(campaign_id=1, stat_date=DAY1, add_to_cart=7, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, campaign_totals=campaign_totals)

    assert _cell(rows, "carts", 0, "manual_search") == 7
    assert _cell(rows, "carts_assoc", 0, "manual_search") is None
    assert _cell(rows, "orders_assoc", 0, "manual_search") is None
