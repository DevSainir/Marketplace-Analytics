"""Unit tests for the grain of an advertising column: the whole campaign.

An ad column measures an ad campaign — its spend, its traffic, its
conversions across every card and variant it delivered for. The viewed card's
own share of it is a separate fact, and only two columns are built from that
share: «Общая» (the card's whole day) and «Органика» (that day minus the ads).

The distinction is invisible while a campaign promotes one card, which is how
this account runs them — so these fixtures deliberately give a campaign more
than the card on screen, which is the only way the two grains can be told apart.
"""

from __future__ import annotations

from tests.support.matrix_rows import (
    DAY1,
    _ad_row,
    _campaign,
    _campaign_total,
    _cell,
    _funnel_row,
    _matrix,
    _price_row,
)


def _two_card_campaign() -> dict[str, list[float | None]]:
    """A shelves campaign promoting two cards; the viewed one is a third of it.

    The campaign spent 3 000 ₽ for 300 impressions, 30 clicks, 15 carts and 8 orders;
    1 000 ₽ / 100 / 10 / 5 / 2 of that was booked on the card being viewed.
    """
    return _matrix(
        campaigns={1: _campaign(1, "manual", search=False, shelves=True)},
        ad_rows=[_ad_row(1, DAY1, views=100, clicks=10, add_to_cart=5, spend=1000, orders=2)],
        campaign_totals=[
            _campaign_total(
                1,
                DAY1,
                views=300,
                clicks=30,
                add_to_cart=15,
                spend=3000,
                orders=8,
                traffic_add_to_cart=15,
                traffic_orders=8,
            )
        ],
        funnel_rows=[_funnel_row(DAY1, open_count=400, cart_count=40, order_count=12)],
        price_snapshots=[_price_row(DAY1, seller=1000)],
    )


def test_an_ad_column_reads_the_whole_campaign() -> None:
    """Spend, traffic and conversions in the column are the campaign's own."""
    rows = _two_card_campaign()

    assert _cell(rows, "spend", 0, "manual_shelves") == 3000
    assert _cell(rows, "views", 0, "manual_shelves") == 300
    assert _cell(rows, "clicks", 0, "manual_shelves") == 30
    assert _cell(rows, "carts", 0, "manual_shelves") == 15
    assert _cell(rows, "orders", 0, "manual_shelves") == 8
    # The card's own share rides alongside, for the hover.
    assert _cell(rows, "carts_sku", 0, "manual_shelves") == 5
    assert _cell(rows, "orders_sku", 0, "manual_shelves") == 2


def test_the_columns_money_and_efficiency_follow_that_grain() -> None:
    """Its ₽ and per-conversion costs divide the campaign's own numbers."""
    rows = _two_card_campaign()

    assert _cell(rows, "order_sum", 0, "manual_shelves") == 8000.0  # 8 x 1 000 ₽
    assert _cell(rows, "cost_per_order", 0, "manual_shelves") == 375.0  # 3 000 / 8
    assert _cell(rows, "cost_per_cart", 0, "manual_shelves") == 200.0  # 3 000 / 15
    assert _cell(rows, "drr_orders", 0, "manual_shelves") == 37.5  # 3 000 / 8 000 ₽


def test_the_cards_own_columns_keep_the_cards_own_share() -> None:
    """«Общая» and «Органика» stay the card's — never the campaign's.

    «Общая» is this card's day: crediting it with a campaign's whole spend
    would overstate its DRR by however much the campaign spent on other cards,
    and «Органика» (funnel minus ads) would go negative on the counts.
    """
    rows = _two_card_campaign()

    assert _cell(rows, "spend", 0, "total") == 1000.0
    assert _cell(rows, "views", 0, "total") == 100
    assert _cell(rows, "clicks", 0, "organic") == 390  # 400 opens - the card's 10
    assert _cell(rows, "carts", 0, "organic") == 35  # 40 - the card's 5
    assert _cell(rows, "orders", 0, "organic") == 10  # 12 - the card's 2


def test_a_siblings_campaign_does_not_claim_a_column_here() -> None:
    """A campaign that never advertised THIS card paints no column on its page.

    WB books a campaign's conversions on whichever variant the buyer picked, so
    a card collects orders from campaigns promoting its siblings — with no
    traffic and no spend of its own (for example, 2 orders of a campaign that
    spent its whole budget advertising another card). Judged by
    the campaign's numbers such a campaign clears every significance test and,
    ranked by impressions, displaces the campaign that actually runs here.

    So what a column SHOWS is the whole campaign; what puts it on this page is
    the card's own delivery.
    """
    rows = _matrix(
        campaigns={
            1: _campaign(1, "manual", search=False, shelves=True),
            2: _campaign(2, "manual", search=True, shelves=False),
        },
        ad_rows=[
            # The campaign that advertises this card.
            _ad_row(1, DAY1, views=1000, clicks=50, add_to_cart=20, spend=8000, orders=22),
            # A sibling's campaign: conversions booked here, no traffic, no spend.
            _ad_row(2, DAY1, views=0, clicks=0, add_to_cart=5, spend=0, orders=2),
        ],
        campaign_totals=[
            _campaign_total(1, DAY1, views=1200, clicks=60, add_to_cart=30, spend=9000, orders=32),
            # Far bigger than the campaign that runs here, on another card.
            _campaign_total(
                2, DAY1, views=9000, clicks=400, add_to_cart=166, spend=8027, orders=82
            ),
        ],
        funnel_rows=[_funnel_row(DAY1, open_count=400, cart_count=40, order_count=40)],
    )

    assert _cell(rows, "spend", 0, "manual_shelves") == 9000  # the card's campaign
    assert _cell(rows, "orders", 0, "manual_shelves") == 32
    # …and the sibling's campaign is nowhere in this card's columns.
    assert _cell(rows, "spend", 0, "manual_search") is None
    assert _cell(rows, "orders", 0, "manual_search") is None
