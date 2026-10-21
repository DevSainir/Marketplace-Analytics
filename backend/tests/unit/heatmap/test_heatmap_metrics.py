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
    spread_bonus,
)


def _funnel_day(**over: object) -> Facts:
    """A SKU-day the funnel reported: 10 orders at 10 000 ₽, WB's sum 10 370 KGS."""
    facts = Facts(funnel_days=1, opens=100, carts=20, orders=10, priced_orders=10)
    facts.amount_seller = Decimal("10000")
    facts.valued_orders = 10
    facts.order_value = Decimal("10370")
    facts.order_currencies = frozenset({"KGS"})
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


def test_the_orders_in_money_are_wbs_own_funnel_sum() -> None:
    assert read_metric("order_sum", _funnel_day()) == 10370.0


def test_drr_divides_kgs_spend_by_wbs_kgs_order_sum() -> None:
    """DRR on orders is som over som, with no exchange rate of ours in between."""
    cell = _funnel_day(ad_days=1, ad_currencies=frozenset({"KGS"}))
    cell.spend = Decimal("1037")

    assert read_metric("drr_orders", cell) == 10.0


def test_drr_of_rub_spend_against_kgs_orders_is_unknown() -> None:
    """Roubles over som is off by the day's rate — «—» until we convert."""
    cell = _funnel_day(ad_days=1, ad_currencies=frozenset({"RUB"}))
    cell.spend = Decimal("1037")

    assert read_metric("drr_orders", cell) is None
    assert read_metric("spend", cell) == 1037.0


def test_drr_is_unknown_when_wb_valued_only_part_of_the_orders() -> None:
    """A week with a day WB served no sum for has no order sum in one currency."""
    cell = _funnel_day(ad_days=1, ad_currencies=frozenset({"KGS"}), valued_orders=7)
    cell.spend = Decimal("1500")

    assert read_metric("order_sum", cell) is None
    assert read_metric("drr_orders", cell) is None


def test_spend_over_two_currencies_has_no_figure() -> None:
    """A week across 20.08: a RUB and a KGS campaign cannot be added up."""
    rub = Facts(ad_days=1, spend=Decimal("900"), ad_views=1000, ad_clicks=10)
    rub.ad_currencies = frozenset({"RUB"})
    kgs = Facts(ad_days=1, spend=Decimal("800"), ad_views=900, ad_clicks=9)
    kgs.ad_currencies = frozenset({"KGS"})
    week = Facts()

    merge_days(week, rub)
    merge_days(week, kgs)

    for metric in ("spend", "cpc", "cpm", "cpo"):
        assert read_metric(metric, week) is None, metric
    assert read_metric("ctr", week) == 1.0


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


def test_profit_charges_only_what_the_ads_cost_the_seller() -> None:
    """WB's bonus share of the spend never left the seller's account; the P&L does not charge it."""
    cell = Facts(finance_known=True, payout_net=Decimal("3000"), cogs=Decimal("1200"))
    cell.settled_spend = Decimal("300")
    cell.settled_bonus = Decimal("100")

    assert read_metric("profit", cell) == 1600.0


def test_the_bonus_is_laid_over_the_days_by_their_spend() -> None:
    """The ledger knows only the window; each day takes the share of it its spend earned."""
    monday = Facts(finance_known=True, spend=Decimal("100"))
    tuesday = Facts(finance_known=True, spend=Decimal("300"))
    facts = {(1, date(2026, 9, 21)): monday, (1, date(2026, 9, 22)): tuesday}

    spread_bonus(facts, {1: Decimal("200")})

    assert (monday.settled_bonus, tuesday.settled_bonus) == (Decimal("50"), Decimal("150"))


def test_the_bonus_never_exceeds_the_spend() -> None:
    """A write-off for impressions just outside the window must not make ads cost negative."""
    day = Facts(finance_known=True, spend=Decimal("100"))

    spread_bonus({(1, date(2026, 9, 21)): day}, {1: Decimal("900")})

    assert day.settled_bonus == Decimal("100")


def test_an_unsettled_day_carries_no_bonus() -> None:
    """Its spend is not charged against profit yet, so neither is its bonus."""
    settled = Facts(finance_known=True, spend=Decimal("100"))
    pending = Facts(spend=Decimal("100"))
    facts = {(1, date(2026, 9, 21)): settled, (1, date(2026, 9, 28)): pending}

    spread_bonus(facts, {1: Decimal("100")})

    assert (settled.settled_bonus, pending.settled_bonus) == (Decimal("50"), Decimal(0))
