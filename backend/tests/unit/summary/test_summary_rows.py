"""The per-article rows «Выручка по категории» is folded from.

The block itself — grouping by subject or brand, sorting, folding the tail — is
the page's work now, because a reader changes those several times a minute and
each change used to cost a round trip over the whole settlement window. What
stays here is the one rule about which rows exist at all.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.summary.services.compose import build_rows
from tests.unit.summary.builders import make_report, make_row


def test_account_level_money_never_becomes_a_row() -> None:
    """Storage, acceptance and the ad invoices have no article, so no row.

    Every way of dividing them between articles would be an invention. They
    stay in the headline, where they belong, and out of a ranking of who earned
    what — which is why the rows are built from ``rows`` and never from
    ``totals``.
    """
    rows = [
        make_row(nm_id=1, revenue="600", payout_net="500", cost_price="10", net_profit="300"),
        make_row(nm_id=2, revenue="400", payout_net="300", cost_price="10", net_profit="100"),
    ]
    # Totals carry 200 less margin than the rows: that is the account-level money.
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="10", net_profit="200")

    built = build_rows(make_report(rows, totals=totals))

    assert [row.nm_id for row in built] == [1, 2]
    assert sum(row.margin or Decimal(0) for row in built) == Decimal("400")


def test_an_uncosted_article_carries_no_margin_rather_than_zero() -> None:
    """A row without a cost price reports nothing, not a margin against free goods.

    Folded into a brand or a subject, a zero would quietly raise that group's
    margin; ``None`` makes the whole group withhold instead, which is the honest
    reading and the one the page implements.
    """
    rows = [
        make_row(nm_id=1, revenue="600", payout_net="500", cost_price="10", net_profit="300"),
        make_row(nm_id=2, revenue="400", payout_net="300", cost_price=None, net_profit=None),
    ]
    totals = make_row(nm_id=0, revenue="1000", payout_net="800", cost_price="10", net_profit="300")

    built = build_rows(make_report(rows, totals=totals))

    assert built[0].margin == Decimal("300")
    assert built[1].margin is None


def test_a_row_carries_both_bases_and_its_catalogue_identity() -> None:
    """Subject and brand travel with every row, so the page can fold by either.

    Sending pre-grouped buckets meant a new request to change the grouping; the
    identity is two short strings and it rides along for free.
    """
    row = make_row(
        nm_id=1,
        revenue="600",
        payout_net="500",
        cost_price="10",
        net_profit="300",
        subject="Брюки",
        brand="NORTH LINE",
    )
    totals = make_row(nm_id=0, revenue="600", payout_net="500", cost_price="10", net_profit="300")

    built = build_rows(make_report([row], totals=totals))[0]

    assert (built.subject, built.brand) == ("Брюки", "NORTH LINE")
    assert (built.revenue_paid, built.revenue_seller) == (Decimal("600"), Decimal("1200"))


def test_an_empty_window_produces_no_rows_rather_than_an_error() -> None:
    """A window with no settlements renders as empty, never as a 500."""
    totals = make_row(
        nm_id=0, revenue="0", payout_net="0", cost_price=None, net_profit=None, sold_units=0
    )

    assert build_rows(make_report([], totals=totals)) == []
