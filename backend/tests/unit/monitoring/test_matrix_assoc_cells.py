"""Unit tests for the associative-conversion cells of the BUILT metrics matrix.

The sibling ``test_matrix_assoc.py`` covers the decomposition itself — how
``derive_base_state`` apportions a campaign's all-variant totals across the
SKUs behind them. This module covers what survives into the rendered table: that a carts/orders
cell IS the кампания's count, that the card's own share rides beside it (the
``*_sku`` rows behind the hover) and is split across a campaign's two zones with
it, that the share is suppressed when there is no gap, and that every ₽ and
efficiency cell of an ad column divides the campaign's counts rather than the
card's slice of them.
"""

from __future__ import annotations

from datetime import timedelta

from tests.support.matrix_rows import (
    DAY1,
    _ad_row,
    _campaign,
    _campaign_total,
    _cell,
    _funnel_row,
    _matrix,
    _price_row,
    _search_row,
)


# --------------------------------------------------------------------------- #
# Associative conversions («100(71)»): campaign-level all-variant totals
# decorating the SKU's own carts/orders cells.
# --------------------------------------------------------------------------- #
def test_the_cell_is_the_campaigns_count_with_the_cards_share_beside_it() -> None:
    """A single-zone campaign's cell reads the кампания; the card's share rides along."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=71, spend=5000, orders=30)]
    campaign_totals = [_campaign_total(1, DAY1, add_to_cart=100, orders=48)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, campaign_totals=campaign_totals)

    # The campaign's counts — associated size/colour variants included — ARE
    # the cells…
    assert _cell(rows, "carts", 0, "manual_search") == 100
    assert _cell(rows, "orders", 0, "manual_search") == 48
    # …with the viewed card's own share behind the hover.
    assert _cell(rows, "carts_sku", 0, "manual_search") == 71
    assert _cell(rows, "orders_sku", 0, "manual_search") == 30
    # The card-share rows never leak into «Общая»/«Органика».
    assert _cell(rows, "carts_sku", 0, "total") is None
    assert _cell(rows, "carts_sku", 0, "organic") is None


def test_assoc_extra_split_by_sku_zone_share() -> None:
    """A split campaign apportions the associative extra by the SKU's own split."""
    campaigns = {1: _campaign(1, "unified", search=True, shelves=True)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=10, spend=5000, orders=5)]
    search_rows = [_search_row(1, DAY1, views=30, clicks=3, add_to_cart=4, spend=1500, orders=2)]
    campaign_totals = [_campaign_total(1, DAY1, add_to_cart=20, orders=9)]

    rows = _matrix(
        campaigns=campaigns,
        ad_rows=ad_rows,
        search_rows=search_rows,
        campaign_totals=campaign_totals,
    )

    # Carts: extra 10 splits 4/10 -> search +4, shelves +6.
    assert _cell(rows, "carts_sku", 0, "uni_search") == 4
    assert _cell(rows, "carts", 0, "uni_search") == 8
    assert _cell(rows, "carts_sku", 0, "uni_shelves") == 6
    assert _cell(rows, "carts", 0, "uni_shelves") == 12
    # Orders: extra 4 splits 2/5 -> search +2, shelves +2; leg sums stay exact.
    assert _cell(rows, "orders", 0, "uni_search") == 4
    assert _cell(rows, "orders", 0, "uni_shelves") == 5


def test_the_card_share_is_hidden_without_a_gap() -> None:
    """No associated-variant conversions -> the card IS the cell, no share row."""
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=7, spend=5000, orders=3)]
    campaign_totals = [_campaign_total(1, DAY1, add_to_cart=7, orders=3)]

    rows = _matrix(campaigns=campaigns, ad_rows=ad_rows, campaign_totals=campaign_totals)

    assert _cell(rows, "carts", 0, "manual_search") == 7
    assert _cell(rows, "carts_sku", 0, "manual_search") is None
    assert _cell(rows, "orders_sku", 0, "manual_search") is None


# --------------------------------------------------------------------------- #
# The campaign's counts are what the ₽ and efficiency rows divide: an ad column
# measures a рекламная кампания, so its revenue is the revenue the campaign
# brought — associated size/colour variants included.
# --------------------------------------------------------------------------- #
def _assoc_money_rows() -> dict[str, list[float | None]]:
    """A search campaign that delivered 32 orders, 22 of them on the viewed card.

    Priced at 3 820.25 ₽ with a matured 50% buyout cohort behind it, so the two
    ₽ rows and both ДРР are checkable to the ruble.
    """
    campaigns = {1: _campaign(1, "manual", search=True, shelves=False)}
    ad_rows = [_ad_row(1, DAY1, views=1000, clicks=100, add_to_cart=40, spend=12000, orders=22)]
    campaign_totals = [_campaign_total(1, DAY1, add_to_cart=50, orders=32)]
    funnel_rows = [
        _funnel_row(DAY1, open_count=200, cart_count=60, order_count=40),
        # Matured cohort inside the lagged window: 5 buyouts + 5 refusals -> 50%.
        _funnel_row(DAY1 - timedelta(days=10), order_count=10, buyout_count=5, cancel_count=5),
    ]
    return _matrix(
        campaigns=campaigns,
        ad_rows=ad_rows,
        campaign_totals=campaign_totals,
        funnel_rows=funnel_rows,
        price_snapshots=[_price_row(DAY1, seller=3820.25)],
    )


def test_ad_revenue_counts_every_variant_the_campaign_sold() -> None:
    """«Заказы, ₽» prices the campaign's 32 orders, not the card's own 22."""
    rows = _assoc_money_rows()

    assert _cell(rows, "orders", 0, "manual_search") == 32
    assert _cell(rows, "orders_sku", 0, "manual_search") == 22
    assert _cell(rows, "order_sum", 0, "manual_search") == 122248.0  # 32 x 3 820.25
    # «Выкупы, ₽» rides the same count through the day's buyout percent.
    assert _cell(rows, "buyout_sum", 0, "manual_search") == 61124.0  # 50% of it


def test_ad_efficiency_divides_the_campaigns_counts() -> None:
    """Both ДРР and the cost-per rows judge the campaign by what IT delivered."""
    rows = _assoc_money_rows()

    # 12 000 ₽ over 122 248 ₽ ordered, and over 61 124 ₽ bought out.
    assert _cell(rows, "drr_orders", 0, "manual_search") == 9.82
    assert _cell(rows, "drr_sales", 0, "manual_search") == 19.63
    assert _cell(rows, "cost_per_order", 0, "manual_search") == 375.0  # 12 000 / 32
    assert _cell(rows, "cost_per_cart", 0, "manual_search") == 240.0  # 12 000 / 50
    # …and the конверсия between them stays inside the same campaign-level pair.
    assert _cell(rows, "order_conversion", 0, "manual_search") == 64.0  # 32 / 50


def test_organic_still_subtracts_only_the_cards_own_ad_orders() -> None:
    """«Органика» is the funnel minus what the ads booked ON THIS CARD.

    The funnel counts are the card's own, so subtracting the campaign's
    all-variant total would credit this card's organic column for orders that
    were never booked on it — 40 - 22, never 40 - 32.
    """
    rows = _assoc_money_rows()

    assert _cell(rows, "orders", 0, "organic") == 18
    assert _cell(rows, "carts", 0, "organic") == 20  # 60 - 40, the card's own
