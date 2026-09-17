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
from src.modules.summary.services.compose import build_days, build_kpi, window_ad_cash
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
        buyout_orders=None if None is None else 100,
        ad_cash=None,
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
        buyout_orders=None if None is None else 100,
        ad_cash=Decimal("100"),
        settled_advertising=ZERO,
    )

    # payout_net 800 − cogs 300 (30 × 10 units) − ad cash 100
    assert kpi.margin == Decimal("400")


def test_advertising_is_subtracted_once_and_the_invoice_is_not_the_copy() -> None:
    """«К перечислению» is already net of WB's weekly invoice.

    Adding it back before taking off the real burn is what keeps the charge from
    landing twice. Found on live data, not in review: the card read 2 657 954.54
    against a true 4 313 444.72 over one 54-day window, and the gap was exactly
    that window's 1 993 394.61 of «WB Продвижение» invoices. Revenue reconciled
    throughout, because revenue is the one figure the restatement does not touch.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    # payout_net 800 is already net of a 200 invoice.
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_orders=None if None is None else 100,
        ad_cash=Decimal("150"),
        settled_advertising=Decimal("200"),
    )

    # 800 + 200 invoice back − 300 cogs − 150 actually burned.
    assert kpi.margin == Decimal("550")


def test_without_ad_coverage_the_invoice_stays_inside_the_payout() -> None:
    """No burn to swap in means nothing to swap WB's invoice for.

    Adding the invoice back against an advertising cost we do not have would
    report a window as having spent nothing on ads — the one direction that
    flatters the figure.
    """
    row = make_row(nm_id=1, revenue="1000", payout_net="800", cost_price="30", net_profit="500")
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="30", net_profit="500")

    kpi = build_kpi(
        report=make_report([row], totals=totals),
        orders=None,
        buyouts=None,
        buyout_orders=None if None is None else 100,
        ad_cash=None,
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
        buyout_orders=None if None is None else 100,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert kpi.margin is None


def test_both_counters_of_the_buyout_travel_rather_than_a_ratio() -> None:
    """Units, orders and WB's own counter go out raw; the page divides them.

    «Выкуп» is settled units over orders so it agrees with the two cards beside
    it — a reader divides those in their head, and a third number in that
    position reads as an error. WB's direct counter is carried alongside, and
    neither ratio is computed here: a percentage is presentation, and computing
    it server-side is what would force a round trip to change a price base.
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
        buyout_orders=None if 27 == None else 100,
        ad_cash=None,
        settled_advertising=ZERO,
    )

    assert (kpi.sold_units, kpi.orders, kpi.buyouts) == (30, 100, 27)


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
        buyout_orders=None if None is None else 100,
        ad_cash=None,
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
        buyout_orders=None if None is None else 100,
        ad_cash=None,
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
        costed=True,
    )

    assert [day.ad_spend for day in days] == [Decimal("25.00"), Decimal("75.00")]
    assert sum(day.ad_spend or ZERO for day in days) == window_ad_cash(days, covered=True)


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
    кабинет sold nothing.
    """
    days = build_days(
        buckets=[make_day(day=date(2026, 7, 19), revenue="1000", margin_profit="500")],
        order_days=[
            OrderDay(
                stat_date=date(2026, 7, 21),
                orders=55,
                buyouts=15,
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
    """«Штрафы и удержания» excludes the money the ДРР card already reports.

    WB withholds advertising as an invoice inside «Удержания», so a card that
    summed that line whole would show the same spend twice — once as a
    withholding, once as advertising — and a seller reading both would conclude
    the кабинет paid for it twice.
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
        buyout_orders=None if None is None else 100,
        ad_cash=Decimal("22000"),
        settled_advertising=Decimal("25000"),
    )

    assert kpi.penalties == Decimal("9000")
    assert kpi.ad_spend == Decimal("22000")


def test_the_card_counts_the_advertising_of_the_days_it_has_revenue_for() -> None:
    """Advertising a window cannot yet have earned on is not charged to it.

    A window routinely runs past the last settlement: WB calculates weekly and
    serves late while the promotion statistics land daily. Counting that tail's
    spend against revenue that does not exist yet inflated «Средний ДРР» to
    16.22 % on a live кабинет whose worst DRAWN day was 10.49 % — and
    understated the margin by the same money.
    """
    days = build_days(
        buckets=[make_day(day=date(2026, 9, 13), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[
            AdSpendDay(stat_date=date(2026, 9, 13), spend=Decimal("100"), bonus=ZERO),
            AdSpendDay(stat_date=date(2026, 9, 14), spend=Decimal("400"), bonus=ZERO),
        ],
        costed=True,
    )

    assert window_ad_cash(days, covered=True) == Decimal("100")


def test_without_advertising_coverage_the_answer_is_unknown_rather_than_zero() -> None:
    """A кабинет we have no promotion statistics for has not advertised for free."""
    days = build_days(
        buckets=[make_day(day=date(2026, 9, 13), revenue="1000", margin_profit="500")],
        order_days=[],
        ad_days=[],
        costed=True,
    )

    assert window_ad_cash(days, covered=False) is None
