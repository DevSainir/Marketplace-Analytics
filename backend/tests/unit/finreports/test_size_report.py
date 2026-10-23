"""Unit tests for the per-size cut of one article (the size sub-table).

The measured columns below are a synthetic pair of sizes of one colour — nm
900000101 (m-trx01-blk), sizes 42/162-169 and 42/170-177 — built from round base
numbers so every expected figure can be checked by hand, and so a refactor
cannot quietly redefine what a size line means. The withholding columns a size
almost never carries (storage, acceptance, deductions) are left at zero, which is
what they are on real size rows too.

What earns a test here:

* **Σ sizes = the article.** The whole claim of the cut is that it regroups the
  article's own rows rather than allocating anything. If that ever stops being
  true the drill-down becomes a second, disagreeing report.
* **The buyout is measured against logistics legs, not orders.** The funnel has no
  size; the forward leg is the only size-carrying record of a unit reaching a
  buyer.
* **"Price" is at the seller's price**, the same base as "Revenue" beside it, so
  price x units reads back as the revenue.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.finreports.repos.pnl.sizes import SizeSettlement
from src.modules.finreports.services.pnl.size_report import NO_SIZE_LABEL, build_size_rows


def _size(ts_name: str, **overrides: object) -> SizeSettlement:
    """A size aggregate; the zeros are the columns these rows really carry."""
    values: dict[str, object] = {
        "ts_name": ts_name,
        "sold_units": 0,
        "returned_units": 0,
        "delivered_units": 0,
        "sales_gross": Decimal(0),
        "returns_gross": Decimal(0),
        "sales_before_spp": Decimal(0),
        "returns_before_spp": Decimal(0),
        "payout_sales": Decimal(0),
        "payout_returns": Decimal(0),
        "payout_other": Decimal(0),
        "logistics_forward": Decimal(0),
        "logistics_return": Decimal(0),
        "logistics_unlegged": Decimal(0),
        "penalties": Decimal(0),
        "storage": Decimal(0),
        "acceptance": Decimal(0),
        "deductions": Decimal(0),
        "additional_payments": Decimal(0),
        "rebill_logistic_cost": Decimal(0),
        "rows": 0,
    }
    values.update(overrides)
    return SizeSettlement(**values)  # type: ignore[arg-type]


#: 42/162-169 — a slow size: 25 units carried, 10 bought out, no returns.
SMALL = _size(
    "42/162-169",
    sold_units=10,
    returned_units=0,
    delivered_units=25,
    sales_gross=Decimal("24000.00"),
    sales_before_spp=Decimal("30000.00"),
    payout_sales=Decimal("19200.00"),
    logistics_forward=Decimal("2875.00"),
    rows=50,
)

#: 42/170-177 — the workhorse of the same colour, and the one that pays the
#: return leg: 10 of its 120 bought-out units came back.
BIG = _size(
    "42/170-177",
    sold_units=120,
    returned_units=10,
    delivered_units=480,
    sales_gross=Decimal("288000.00"),
    returns_gross=Decimal("24000.00"),
    sales_before_spp=Decimal("360000.00"),
    returns_before_spp=Decimal("30000.00"),
    payout_sales=Decimal("230400.00"),
    payout_returns=Decimal("19200.00"),
    logistics_forward=Decimal("57600.00"),
    logistics_return=Decimal("4800.00"),
    rows=1100,
)


def test_payout_is_net_of_the_size_own_withholdings() -> None:
    """The payout uses the article's formula, applied to this size's rows."""
    rows = build_size_rows([BIG])

    # 230 400.00 - 19 200.00 - (57 600.00 + 4 800.00)
    assert rows[0].payout_net == Decimal("148800.00")


def test_buyout_is_measured_against_forward_legs() -> None:
    """Sold over units WB actually carried — the only size-carrying denominator."""
    small, big = build_size_rows([SMALL, BIG])

    assert small.buyout_pct == Decimal("40.00")  # 10 / 25
    assert big.buyout_pct == Decimal("25.00")  # 120 / 480


def test_price_is_the_seller_s_price_per_bought_out_unit() -> None:
    """Net revenue before SPP over net units — the base "Revenue" uses.

    It was what buyers paid, beside a revenue at the seller's price, so on the
    same row 5 units x "Price" did not come to "Revenue".
    """
    rows = build_size_rows([BIG])

    # (360 000.00 - 30 000.00) / (120 - 10)
    assert rows[0].average_price == Decimal("3000.00")


def test_rows_wb_bills_without_a_size_are_a_row_of_their_own() -> None:
    """Folding them into a neighbour would break the reconciliation above."""
    nameless = _size("", penalties=Decimal("1750.00"), rows=3)
    rows = build_size_rows([nameless, BIG])

    assert rows[0].ts_name == NO_SIZE_LABEL
    assert rows[0].penalties_total == Decimal("1750.00")


def test_logistics_per_delivery_prices_one_trip() -> None:
    """What a single leg to a buyer costs — the figure a size is priced on."""
    rows = build_size_rows([SMALL])

    assert rows[0].logistics_per_delivery == Decimal("115.00")  # 2 875.00 / 25


def test_an_article_with_no_rows_reports_nothing_rather_than_zero_ratios() -> None:
    """An empty window is an empty list, not a row of «0 %»."""
    assert build_size_rows([]) == []
