"""The «Сводка» cards and its daily series, against hand-written figures.

Both are pure functions over DTOs the finreports and monitoring contracts
already produced, so they are provable here rather than in a tier that needs
Postgres.

The cases cover the decisions this page makes that the per-SKU report does not:
withholding the margin when a cost price is missing, charging WB's advertising
exactly once, and spreading the bonus over the window rather than the day.
Percentages and the price base are NOT among them — those moved to the page,
which is why every figure here carries both bases and no ratios.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.monitoring.contract import AdSpendDay, OrderDay
from src.modules.summary.services.compose import (
    build_days,
    build_kpi,
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
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )

    assert kpi.margin is None
    assert kpi.uncosted_skus == 1


def test_a_fully_costed_window_reports_its_margin() -> None:
    """With every settled SKU costed, the margin is payout less cost and ad cash."""
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )

    # payout_net 800 − cogs 300 (30 × 10 units); the invoice is already inside.
    assert kpi.margin == Decimal("500")


def test_advertising_is_charged_once_as_wbs_invoice() -> None:
    """«К перечислению» is already net of WB's weekly invoice, and the invoice is the total.

    Taking the burn off as well charged it twice, and the card came out well
    below the true margin over a 54-day window. Since 2026-10-02 the card
    charges the invoice, as the P&L's «Итого» does.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    # payout_net 800 is already net of a 200 invoice.
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=Decimal("200"),
    )

    # 800 (already net of the 200 invoice) − 300 cogs.
    assert kpi.margin == Decimal("500")
    assert kpi.ad_spend == Decimal("200")


def test_the_invoice_stays_inside_the_payout() -> None:
    """WB's invoice is withheld inside «к перечислению»; nothing is added back."""
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=Decimal("200"),
    )

    # 800 − 300 cogs, and the 200 invoice left where the settlement put it.
    assert kpi.margin == Decimal("500")


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
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )

    assert kpi.margin is None


def test_the_buyout_counter_travels_with_its_own_denominator() -> None:
    """Bought out and ANSWERED go out raw; the page divides them.

    The denominator is deliveries the buyer answered — bought out or refused —
    which is WB's own definition and the one «Сравнение SKU» has always used.
    Dividing by ORDERS instead is what made this card climb for three weeks
    after every order: an order still in transit counted against the rate as
    though it had been refused. Illustratively, the orders-based figure reads
    16 % on a week-old cohort and 26 % on a month-old one, while the
    answered-based figure reads 27.8 % and 26.6 %.
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
        orders=100,
        buyouts=27,
        buyout_decided=100,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )

    assert (kpi.sold_units, kpi.orders) == (30, 100)
    assert (kpi.buyouts, kpi.buyout_decided) == (27, 100)


def test_no_funnel_coverage_is_not_zero_orders() -> None:
    """Without funnel coverage the orders card is empty, not zero.

    Zero would be a claim that nobody ordered, which is a different and much
    more alarming statement than "the harvest does not reach this window".
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )

    assert kpi.orders is None
    assert kpi.buyouts is None


def test_both_price_bases_travel_on_every_figure() -> None:
    """Switching «Цена реализации» ⇄ «Цена селлера» must cost nothing.

    Sending one base and re-requesting for the other put a round trip over the
    whole settlement window behind a toggle — seconds, for a division the page
    could do instantly. Both now travel, on the cards and on every day.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=ZERO,
    )
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[],
        costed=True,
    )

    # The builders put the seller price at twice the paid one.
    assert (kpi.revenue_paid, kpi.revenue_seller) == (Decimal("1000"), Decimal("2000"))
    assert (days[0].revenue_paid, days[0].revenue_seller) == (Decimal("1000"), Decimal("2000"))


def test_the_weekly_invoice_is_spread_over_the_days_by_their_burn() -> None:
    """A day's margin drops the invoice from its closing day and takes its share instead.

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
        costed=True,
    )

    # The 700 invoice goes back and comes off again in proportion to each day's
    # burn (100 and 100): 100 + 700 − 350, and 800 − 350.
    assert days[0].margin == Decimal("450")
    assert days[1].margin == Decimal("450")
    assert sum(day.margin or ZERO for day in days) == Decimal("900")


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
        costed=True,
    )

    assert [day.ad_spend for day in days] == [Decimal("25.00"), Decimal("75.00")]
    assert sum(day.ad_spend or ZERO for day in days) == Decimal("100")


def test_an_uncosted_window_draws_revenue_without_margin() -> None:
    """The daily margin obeys the same rule as the headline: no cost, no line."""
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[],
        costed=False,
    )

    assert days[0].revenue_paid == Decimal("1000")
    assert days[0].margin is None


def test_a_day_the_funnel_misses_has_no_orders_rather_than_zero() -> None:
    """A gap in the funnel harvest must not be drawn as a day of no demand."""
    days = build_days(
        buckets=[
            make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500"),
            make_day(day=date(2026, 7, 20), revenue="1000", margin_profit="500"),
        ],
        order_days=[
            OrderDay(
                stat_date=date(2026, 7, 19),
                orders=40,
                buyouts=12,
                decided=30,
                amount_seller=Decimal("80000"),
                amount_paid=Decimal("70000"),
            )
        ],
        ad_days=[],
        costed=True,
    )

    assert days[0].orders == 40
    assert days[1].orders is None


def test_a_day_wb_has_not_calculated_still_shows_its_orders_and_its_spend() -> None:
    """Orders and advertising are drawn past the last settlement, revenue is not.

    WB calculates settlements weekly and serves them days late while the funnel
    and the promotion statistics land daily, so the freshest three or four days
    of a window have orders and spend and no settlement at all. They used to
    vanish from every chart; now they are days like any other, with revenue left
    as None rather than zero — the line stops instead of reporting that the
    workspace sold nothing.
    """
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[
            OrderDay(
                stat_date=date(2026, 7, 21),
                orders=55,
                buyouts=15,
                decided=40,
                amount_seller=Decimal("110000"),
                amount_paid=Decimal("96000"),
            )
        ],
        ad_days=[AdSpendDay(stat_date=date(2026, 7, 21), spend=Decimal("300"), bonus=ZERO)],
        costed=True,
    )

    assert [entry.day for entry in days] == [date(2026, 7, 19), date(2026, 7, 21)]
    assert days[1].revenue_paid is None
    assert days[1].margin is None
    assert days[1].orders == 55
    assert days[1].ad_spend == Decimal("300")


def test_the_advertising_invoice_is_not_counted_as_a_withholding() -> None:
    """«Штрафы и удержания» excludes the money the DRR card already reports.

    WB withholds advertising as an invoice inside «Удержания», so a card that
    summed that line whole would show the same spend twice — once as a
    withholding, once as advertising — and a seller reading both would conclude
    the workspace paid for it twice.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="100", net_profit="700")
    report = make_report(
        [row],
        totals=make_row(
            nm_id=0,
            revenue="1000",
            payout_net="800",
            cost_price="100",
            net_profit="700",
            penalties_total="4000",
        ),
        other_deductions="30000",
        dashboard_advertising="25000",
    )

    kpi = build_kpi(
        report=report,
        orders=None,
        buyouts=None,
        buyout_decided=None,
        buyout_lagged=False,
        settled_advertising=Decimal("25000"),
    )

    assert kpi.penalties == Decimal("9000")
    assert kpi.ad_spend == Decimal("25000")


def test_an_invoice_with_no_burn_on_its_days_stays_on_the_day_it_was_charged() -> None:
    """Nothing to spread by: the settlement's own day keeps it, and the sum still holds."""
    days = build_days(
        buckets=[
            make_day(day=date(2026, 9, 13), revenue="1000", margin_profit="300", advertising="200"),
            make_day(day=date(2026, 9, 14), revenue="1000", margin_profit="500"),
        ],
        order_days=[],
        ad_days=[],
        costed=True,
    )

    assert [day.margin for day in days] == [Decimal("300"), Decimal("500")]
