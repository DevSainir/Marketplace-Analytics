"""How a heatmap cell turns into a number, and how cells combine into totals.

The rules pinned here are the ones a heatmap gets wrong while still looking
right: a ratio's total averaged instead of re-derived, a stock level summed over
days, a day WB never reported shown as zero, a profit built on a missing cost.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.heatmap.services.metrics import (
    ADDITIVE_FIELDS,
    Facts,
    merge_days,
    merge_skus,
    read_metric,
)


def _funnel_day(**over: object) -> Facts:
    """A SKU-day the funnel reported, with a priced order volume."""
    facts = Facts(funnel_days=1, opens=100, carts=20, orders=10, priced_orders=10)
    facts.amount_seller = Decimal("10000")
    for name, value in over.items():
        setattr(facts, name, value)
    return facts


def test_a_weeks_ctr_is_its_clicks_over_its_views_not_the_mean_of_its_days() -> None:
    """Σ clicks / Σ views — a quiet day's 50 % must not weigh as much as a busy day's 1 %."""
    busy = Facts(ad_days=1, ad_views=10_000, ad_clicks=100)
    quiet = Facts(ad_days=1, ad_views=10, ad_clicks=5)
    week = Facts()

    merge_days(week, busy)
    merge_days(week, quiet)

    assert read_metric("ctr", week) == 1.05


def test_stock_over_a_week_is_the_last_days_level() -> None:
    """Stock is what sat on the shelf at the end of the period, not the sum of every morning."""
    monday = Facts(stock=40, stock_date=date(2026, 9, 21))
    sunday = Facts(stock=12, stock_date=date(2026, 9, 27))
    week = Facts()

    merge_days(week, sunday)
    merge_days(week, monday)

    assert read_metric("stock", week) == 12


def test_stock_across_articles_adds_up() -> None:
    """Two cards on the same day hold the sum of their units."""
    first = Facts(stock=40, stock_date=date(2026, 9, 27))
    second = Facts(stock=12, stock_date=date(2026, 9, 27))
    both = Facts()

    merge_skus(both, first)
    merge_skus(both, second)

    assert read_metric("stock", both) == 52


def test_a_day_the_funnel_never_reported_is_unknown_not_zero() -> None:
    """No funnel row means WB did not tell us — a zero would read as a day with no demand."""
    assert read_metric("orders", Facts(stock=3, stock_date=date(2026, 9, 27))) is None


def test_a_day_without_ads_on_a_reported_day_is_a_real_zero() -> None:
    """A SKU that ran no campaign has no ad row; the funnel row says the day was harvested."""
    assert read_metric("spend", _funnel_day()) == 0.0


def test_drr_divides_spend_by_the_orders_value() -> None:
    """ДРР по заказам — ad spend over what the orders were worth at the seller's price."""
    cell = _funnel_day(ad_days=1)
    cell.spend = Decimal("1500")

    assert read_metric("drr_orders", cell) == 15.0


def test_drr_is_unknown_when_the_orders_were_never_priced() -> None:
    """Orders with no price have no value; spend over nothing is not an infinite ДРР."""
    cell = _funnel_day(ad_days=1, priced_orders=0, amount_seller=Decimal(0))
    cell.spend = Decimal("1500")

    assert read_metric("drr_orders", cell) is None


def test_organic_opens_never_go_negative() -> None:
    """The two feeds count a click slightly differently; a negative organic is an artefact."""
    assert read_metric("organic_opens", _funnel_day(opens=10, ad_clicks=14)) == 0


def test_the_price_of_a_cell_is_weighted_by_its_orders() -> None:
    """Nine orders at 900 and one at 1900 average to 1000, not to 1400."""
    cheap = _funnel_day(orders=9, priced_orders=9, amount_seller=Decimal("8100"))
    dear = _funnel_day(orders=1, priced_orders=1, amount_seller=Decimal("1900"))
    both = Facts()

    merge_skus(both, cheap)
    merge_skus(both, dear)

    assert read_metric("seller_price", both) == 1000.0


def test_profit_is_payout_less_cost_less_the_settled_days_ads() -> None:
    """Payout net of WB's charges, minus goods, minus advertising on settled days only."""
    cell = Facts(finance_known=True, revenue=Decimal("5000"), sold_units=2)
    cell.payout_net = Decimal("3000")
    cell.cogs = Decimal("1200")
    cell.spend = Decimal("900")
    cell.settled_spend = Decimal("300")

    assert read_metric("profit", cell) == 1500.0


def test_profit_is_withheld_when_an_article_has_no_cost_price() -> None:
    """A profit built on a missing cost is revenue wearing a profit's label."""
    costed = Facts(finance_known=True, payout_net=Decimal("3000"), cogs=Decimal("1000"))
    uncosted = Facts(finance_known=True, payout_net=Decimal("2000"), uncosted=True)
    both = Facts()

    merge_skus(both, costed)
    merge_skus(both, uncosted)

    assert read_metric("profit", both) is None


def test_finance_after_the_last_settled_day_is_unknown() -> None:
    """WB settles weekly; a day it has not calculated is not a day with no sales."""
    assert read_metric("revenue", _funnel_day()) is None


def test_margin_is_unknown_on_a_refund_only_cell() -> None:
    """A negative revenue makes a percentage of it meaningless."""
    cell = Facts(finance_known=True, revenue=Decimal("-800"), payout_net=Decimal("-700"))

    assert read_metric("margin", cell) is None


def test_folding_adds_every_additive_fact() -> None:
    """A fact added to the cell later and forgotten in the fold would silently read as zero."""
    one = Facts()
    for name in ADDITIVE_FIELDS:
        setattr(one, name, 1)
    folded = Facts()

    merge_skus(folded, one)
    merge_skus(folded, one)

    assert {name: getattr(folded, name) for name in ADDITIVE_FIELDS} == dict.fromkeys(
        ADDITIVE_FIELDS, 2
    )
