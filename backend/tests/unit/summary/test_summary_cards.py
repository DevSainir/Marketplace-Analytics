"""The «Сводка» cards and its daily series, against hand-written figures.

Both are pure functions over DTOs the finreports and monitoring contracts
already produced, so they are provable here rather than in a tier that needs
Postgres.

The cases cover the three decisions this page makes that the per-SKU report does
not: withholding the margin when a cost price is missing, re-dating WB's weekly
advertising invoice onto the days the ads actually ran, and spreading the bonus
over the window rather than the day.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.monitoring.contract import AdSpendDay, OrderDay
from src.modules.summary.schemas import RevenueBase
from src.modules.summary.services.compose import (
    build_days,
    build_kpi,
    window_ad_cash,
)
from tests.unit.summary.builders import ZERO, make_day, make_report, make_row


def test_one_uncosted_sku_withholds_the_whole_margin() -> None:
    """A window is not given a margin while any settled SKU has no cost price.

    The per-SKU report is softer — it sums the costed rows and counts the rest —
    which is right for a table read row by row and wrong for one headline number,
    where the omission is invisible. A margin computed against goods that were
    implicitly free reads as a good month.
    """
    costed = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    uncosted = make_row(nm_id=2, revenue="500", payout_net="400", cost_price=None, net_profit=None)
    totals = make_row(nm_id=0, revenue="1500", payout_net="1200", cost_price="30", net_profit="900")

    kpi = build_kpi(
        report=make_report([costed, uncosted], totals=totals),
        base=RevenueBase.PAID,
        orders=None,
        buyouts=None,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert kpi.margin is None
    assert kpi.margin_pct is None
    assert kpi.uncosted_skus == 1


def test_a_fully_costed_window_reports_its_margin() -> None:
    """With every settled SKU costed, the margin is payout less cost and ad cash."""
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        base=RevenueBase.PAID,
        orders=None,
        buyouts=None,
        ad_cash=Decimal("100"),
        settled_advertising=ZERO,
    )

    # payout_net 800 − cogs 300 (30 × 10 units) − ad cash 100
    assert kpi.margin == Decimal("400")


def test_advertising_is_subtracted_once_and_the_invoice_is_not_the_copy() -> None:
    """«К перечислению» is already net of WB's weekly invoice; adding it back
    before taking off the real burn is what keeps the charge from landing twice.

    Found on live data, not in review: the card read 3 161 239 against a true
    4 134 120 over one 54-day window, and the gap was exactly that window's
    1 993 395 of «WB Продвижение» invoices. Revenue reconciled throughout,
    because revenue is the one figure the restatement does not touch.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    # payout_net 800 is already net of a 200 invoice.
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        base=RevenueBase.PAID,
        orders=None,
        buyouts=None,
        ad_cash=Decimal("150"),
        settled_advertising=Decimal("200"),
    )

    # 800 + 200 invoice back − 300 cogs − 150 actually burned.
    assert kpi.margin == Decimal("550")


def test_a_refund_only_sku_without_a_cost_still_withholds_the_margin() -> None:
    """Net units of zero is not the test — a refund-only SKU moved goods too.

    Counting only SKUs with positive sales would let a window whose returns
    outweighed its sales report a margin against an unknown cost, which is the
    one direction that flatters the figure.
    """
    refunded = make_row(
        nm_id=2,
        revenue="0",
        payout_net="-200",
        cost_price=None,
        net_profit=None,
        sold_units=0,
        returned_units=4,
    )
    totals = make_row(nm_id=0, revenue="1000", payout_net="600", cost_price="30", net_profit="300")

    kpi = build_kpi(
        report=make_report([refunded], totals=totals),
        base=RevenueBase.PAID,
        orders=None,
        buyouts=None,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert kpi.margin is None


def test_buyout_agrees_with_the_cards_standing_next_to_it() -> None:
    """«Выкуп» is settled units over orders, not WB's own counter.

    The page shows «Продано» and «Заказов» as their own cards, so a reader
    divides them in their head; any third number in that position reads as an
    error. WB's direct counter is still reported, separately.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(
        nm_id=0,
        revenue="1000",
        payout_net="800",
        cost_price="30",
        net_profit="500",
        sold_units=30,
        returned_units=0,
    )

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        base=RevenueBase.PAID,
        orders=100,
        buyouts=27,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert kpi.buyout_pct == Decimal("30.00")
    assert kpi.buyout_counted_pct == Decimal("27.00")


def test_no_funnel_coverage_is_not_zero_orders() -> None:
    """Without funnel coverage the orders card is empty, and so is «Выкуп».

    Zero would be a claim that nobody ordered, which is a different and much
    more alarming statement than "the harvest does not reach this window".
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        base=RevenueBase.PAID,
        orders=None,
        buyouts=None,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert kpi.orders is None
    assert kpi.buyout_pct is None


def test_the_weekly_invoice_is_swapped_for_the_days_own_burn() -> None:
    """A day's margin drops the settlement's invoice and takes the real burn.

    WB withholds advertising once a week, so the settlement charges a whole
    week's ads to whichever day the invoice closed on. Left alone, that day's
    margin craters and the other six sit too high — a shape that is wrong on
    every single day of the chart.
    """
    invoice_day = make_day(
        day=date(2026, 7, 19), revenue="1000", margin_profit="100", advertising="700"
    )
    quiet_day = make_day(day=date(2026, 7, 20), revenue="1000", margin_profit="800")

    days = build_days(
        buckets=[invoice_day, quiet_day],
        order_days=[],
        ad_days=[
            AdSpendDay(stat_date=date(2026, 7, 19), spend=Decimal("100"), bonus=ZERO),
            AdSpendDay(stat_date=date(2026, 7, 20), spend=Decimal("100"), bonus=ZERO),
        ],
        base=RevenueBase.PAID,
        costed=True,
    )

    # 100 + 700 invoice added back − 100 actually burned that day.
    assert days[0].margin == Decimal("700")
    assert days[1].margin == Decimal("700")


def test_the_bonus_is_spread_over_the_window_and_never_exceeds_a_day() -> None:
    """A batched write-off cannot make one day's advertising negative.

    WB books bonuses in batches — one row at 22:45 against a whole day of
    impressions — so a day's own ledger rows routinely exceed that day's spend.
    Taken per day that prints a negative cost; spread over the window in
    proportion to spend it stays non-negative and still sums to the window.
    """
    ad_days = [
        AdSpendDay(stat_date=date(2026, 7, 19), spend=Decimal("100"), bonus=Decimal("300")),
        AdSpendDay(stat_date=date(2026, 7, 20), spend=Decimal("300"), bonus=ZERO),
    ]

    days = build_days(
        buckets=[
            make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500"),
            make_day(day=date(2026, 7, 20), revenue="1000", margin_profit="500"),
        ],
        order_days=[],
        ad_days=ad_days,
        base=RevenueBase.PAID,
        costed=True,
    )

    assert [day.ad_spend for day in days] == [Decimal("25.00"), Decimal("75.00")]
    assert sum(day.ad_spend or ZERO for day in days) == window_ad_cash(ad_days)


def test_an_uncosted_window_draws_revenue_without_margin() -> None:
    """The daily margin obeys the same rule as the headline: no cost, no line."""
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[],
        base=RevenueBase.PAID,
        costed=False,
    )

    assert days[0].revenue == Decimal("1000")
    assert days[0].margin is None


def test_a_day_the_funnel_misses_has_no_orders_rather_than_zero() -> None:
    """A gap in the funnel harvest must not be drawn as a day of no demand."""
    days = build_days(
        buckets=[
            make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500"),
            make_day(day=date(2026, 7, 20), revenue="1000", margin_profit="500"),
        ],
        order_days=[OrderDay(stat_date=date(2026, 7, 19), orders=40, buyouts=12)],
        ad_days=[],
        base=RevenueBase.PAID,
        costed=True,
    )

    assert days[0].orders == 40
    assert days[1].orders is None


def test_the_revenue_base_switches_both_the_cards_and_the_chart() -> None:
    """«Цена карточки» is a different question, not a different rendering.

    WB's СПП is funded by WB, so the pre-discount price is what the payout is
    pegged to; a base that moved the cards without moving the chart would put
    two different questions on one screen.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        base=RevenueBase.SELLER,
        orders=None,
        buyouts=None,
        ad_cash=None,
        settled_advertising=ZERO,
    )
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[],
        base=RevenueBase.SELLER,
        costed=True,
    )

    assert kpi.revenue == Decimal("2000")
    assert days[0].revenue == Decimal("2000")
