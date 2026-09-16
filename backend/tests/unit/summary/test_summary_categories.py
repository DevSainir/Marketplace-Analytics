"""«Выручка по категории» — who produced the window, and what stays out of it.

The block ranks SKUs, subjects or brands. Two rules decide what it may claim:
account-level money raises no bar because it belongs to no product, and a bar
reports no margin at all as soon as one of its SKUs is uncosted.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.summary.schemas import CategoryGrouping, RevenueBase
from src.modules.summary.services.compose import (
    build_categories,
    build_kpi,
)
from tests.unit.summary.builders import ZERO, make_report, make_row


def test_account_level_money_never_reaches_a_category_bar() -> None:
    """Storage, acceptance and the ad invoices have no SKU, subject or brand.

    Every way of dividing them across bars would be an invention. They stay in
    the headline, where they belong, and out of a ranking of who earned what —
    which is why the bars are built from ``rows`` and never from ``totals``.
    """
    rows = [
        make_row(nm_id=1, revenue="600", payout_net="500", cost_price="10", net_profit="300"),
        make_row(nm_id=2, revenue="400", payout_net="300", cost_price="10", net_profit="100"),
    ]
    # Totals carry 200 less margin than the rows: that is the account-level money.
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="10", net_profit="200")

    categories = build_categories(
        report=make_report(rows, totals=totals),
        base=RevenueBase.PAID,
        grouping=CategoryGrouping.SKU,
    )

    assert [category.revenue for category in categories] == [Decimal("600"), Decimal("400")]
    assert sum(category.margin or ZERO for category in categories) == Decimal("400")


def test_a_category_with_one_uncosted_sku_reports_no_margin() -> None:
    """The no-cost rule applies at the bar's own grain, not only the window's.

    A brand whose costed half shows a margin and whose uncosted half shows
    nothing would rank above brands that are fully costed, purely for being
    less well documented.
    """
    rows = [
        make_row(
            nm_id=1,
            revenue="600",
            payout_net="500",
            cost_price="10",
            net_profit="300",
            brand="Полная",
        ),
        make_row(
            nm_id=2,
            revenue="400",
            payout_net="300",
            cost_price=None,
            net_profit=None,
            brand="Неполная",
        ),
    ]
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="10", net_profit="300")

    categories = build_categories(
        report=make_report(rows, totals=totals),
        base=RevenueBase.PAID,
        grouping=CategoryGrouping.BRAND,
    )

    by_label = {category.label: category for category in categories}
    assert by_label["Полная"].margin == Decimal("300")
    assert by_label["Неполная"].margin is None


def test_subjects_fold_their_skus_and_count_them() -> None:
    """Grouping by subject sums the SKUs under it and says how many there were.

    The count is what makes a folded tail honest: a bar labelled «Брюки» that
    hides four SKUs and one that hides forty are different claims.
    """
    rows = [
        make_row(
            nm_id=1,
            revenue="600",
            payout_net="500",
            cost_price="10",
            net_profit="300",
            subject="Брюки",
        ),
        make_row(
            nm_id=2,
            revenue="400",
            payout_net="300",
            cost_price="10",
            net_profit="100",
            subject="Брюки",
        ),
        make_row(
            nm_id=3,
            revenue="200",
            payout_net="150",
            cost_price="10",
            net_profit="50",
            subject="Костюмы",
        ),
    ]
    totals = make_row(nm_id=0, revenue="1200", payout_net="950", cost_price="10", net_profit="450")

    categories = build_categories(
        report=make_report(rows, totals=totals),
        base=RevenueBase.PAID,
        grouping=CategoryGrouping.SUBJECT,
    )

    assert categories[0].label == "Брюки"
    assert categories[0].revenue == Decimal("1000")
    assert categories[0].sku_count == 2
    assert categories[1].sku_count == 1


def test_an_empty_window_is_not_a_division_by_zero() -> None:
    """A window with no settlements renders as empty, never as a 500."""
    totals = make_row(
        nm_id=0,
        revenue="0",
        payout_net="0",
        cost_price=None,
        net_profit=None,
        sold_units=0,
    )

    kpi = build_kpi(
        report=make_report([], totals=totals),
        base=RevenueBase.PAID,
        orders=0,
        buyouts=0,
        ad_cash=None,
    )

    assert kpi.revenue == ZERO
    assert kpi.average_cheque is None
    assert kpi.buyout_pct is None
    assert (
        build_categories(
            report=make_report([], totals=totals),
            base=RevenueBase.PAID,
            grouping=CategoryGrouping.SKU,
        )
        == []
    )
