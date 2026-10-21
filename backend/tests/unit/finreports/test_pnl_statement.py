"""Unit tests for the pure P&L composition.

Pinned against **one synthetic WB weekly report** — ``realizationreport_id=900000201``,
2026-08-10..16, 9 600 settlement rows, KGS — shaped like a real
``reportDetailByPeriod`` week. The figures are invented from round base numbers,
but they are consistent by construction: the footer below is what the rows add up
to, the way WB's own footer is, so a refactor cannot quietly redefine a line — if
one moves, the composition changed.

Four properties earn a test here, each because getting it wrong yields a
plausible statement rather than an error:

* the revenue block reconstructs WB's own ``ppvz_for_pay`` **exactly** — that is
  the only figure WB actually settles on, and a statement whose printed lines do
  not add up to it cannot be reconciled against a bank receipt;
* refunds are subtracted, never summed (WB serves them positive);
* the commission line is derived against the SALE-side payout, so WB's
  standalone compensations are not reported as negative commission;
* the acquiring WB bills separately is a memo, never a deduction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.services.pnl import build_statement

#: The footer of the synthetic week: Σ payout for goods (2 112 000.00) less every
#: withholding column (361 250.00 logistics + 12 000.00 storage + 8 500.00 fines
#: + 150 000.00 deductions).
EXPECTED_PAYOUT_TOTAL = Decimal("1580250.00")


def _week() -> SettlementAggregate:
    """The synthetic reference week's sums, in the shape the repository returns."""
    return SettlementAggregate(
        key=900000201,
        label="",
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 16),
        currency="KGS",
        subject_name="",
        brand_name="",
        sold_units=1200,
        returned_units=150,
        sales_gross=Decimal("3000000.00"),
        returns_gross=Decimal("360000.00"),
        sales_before_spp=Decimal("3600000.00"),
        returns_before_spp=Decimal("432000.00"),
        payout_sales=Decimal("2400000.00"),
        payout_returns=Decimal("288000.00"),
        payout_other=Decimal("0"),
        wb_commission_reported=Decimal("395999.94"),
        wb_commission_vat=Decimal("79200.00"),
        wb_reward=Decimal("0"),
        acquiring_withheld=Decimal("52800.00"),
        acquiring_billed_apart=Decimal("0"),
        agency_vat=Decimal("540000.00"),
        logistics_forward=Decimal("300000.00"),
        logistics_return=Decimal("60000.00"),
        logistics_unlegged=Decimal("1250.00"),
        storage=Decimal("12000.00"),
        acceptance=Decimal("0"),
        penalties=Decimal("8500.00"),
        deductions=Decimal("150000.00"),
        additional_payments=Decimal("0"),
        rebill_logistic_cost=Decimal("0"),
        advertising=Decimal("156000.00"),
        rows=9600,
    )


def _build(aggregate: SettlementAggregate, *, cogs: Decimal = Decimal(0), cogs_units: int = 0):
    """Compose a statement with no drill-downs (they are the repo's business)."""
    return build_statement(
        aggregate,
        key=str(aggregate.key),
        label="неделя",
        cogs=cogs,
        cogs_units=cogs_units,
        logistics_reasons=[],
        storage_reasons=[],
        penalty_reasons=[],
        deduction_reasons=[],
    )


def test_the_week_reproduces_wbs_own_bottom_line() -> None:
    """«Итого к оплате» equals the footer figure of report 900000201.

    1 580 250.00 KGS is the week's ``ppvz_for_pay`` sum less each withholding
    column, worked out by hand from the aggregate above. This is the single
    assertion that ties the statement to its report's footer.
    """
    statement = _build(_week())

    assert statement.payout_total == EXPECTED_PAYOUT_TOTAL


def test_the_revenue_block_reconstructs_the_settled_payout_exactly() -> None:
    """Paid − commission − acquiring − agent's reward == payout for sales.

    Exact, with no tolerance. WB publishes its reward at full precision and again
    rounded to kopecks; adding those to the VAT gives a commission that misses
    the payout by ~0.12 KGS a week, which is why the line is derived as a
    residual instead. If this ever needs a tolerance, that decision was reversed.
    """
    statement = _build(_week())

    residual = (
        statement.revenue_paid
        - statement.wb_commission
        - statement.acquiring
        - statement.wb_reward
        - statement.payout_from_sales
    )

    assert residual == Decimal(0)


def test_the_withholding_block_reconstructs_итого_к_оплате_exactly() -> None:
    """Payout for goods − total withheld == «Итого к оплате»."""
    statement = _build(_week())

    assert statement.payout_for_goods - statement.total_withheld == statement.payout_total


def test_refunds_are_subtracted_not_summed() -> None:
    """Revenue nets refunds off, though WB serves their money POSITIVE.

    Every refund column arrives with the same sign as a sale — WB serves no
    negative refund amounts at all. Add them instead of subtracting and this
    week reports 2 156 250.00 payable instead of 1 580 250.00: a 36 %
    overstatement that still looks like money.
    """
    statement = _build(_week())

    assert statement.revenue_paid == Decimal("3000000.00") - Decimal("360000.00")
    assert statement.payout_from_sales == Decimal("2400000.00") - Decimal("288000.00")


def test_the_logistics_sub_lines_add_up_to_the_logistics_line() -> None:
    """Forward, return and un-legged legs partition ``delivery_rub`` exactly.

    «Коррекция логистики» sets neither leg counter, on any of its rows. Folding
    it into "forward" to make two sub-lines add up reports correction money as
    delivery-to-customer; three honest buckets beat two that balance.
    """
    statement = _build(_week())

    assert (
        statement.logistics_forward + statement.logistics_return + statement.logistics_unlegged
        == statement.logistics.amount
    )
    assert statement.logistics.amount == Decimal("361250.00")


def test_the_discount_line_nets_refunds_on_the_pre_spp_basis() -> None:
    """«Скидка WB» is the gap between the seller's price and what buyers paid.

    Both sides net refunds at the *same* basis. Netting the pre-SPP revenue by
    the refunds' post-SPP amount instead mixes two bases and inflates the
    discount by the refunds' own SPP — 72 000.00 KGS in this one week.
    """
    statement = _build(_week())

    assert statement.revenue_seller_price == Decimal("3600000.00") - Decimal("432000.00")
    assert statement.wb_discount == statement.revenue_seller_price - statement.revenue_paid


def test_compensations_are_not_reported_as_negative_commission() -> None:
    """WB's standalone compensations raise the payout, never lower the commission.

    They land in ``ppvz_for_pay`` and no other money column, so deriving the
    commission against the *total* payout would book them as a commission
    refund — a year of compensations would read as WB charging less than it did.
    """
    with_compensation = _build(_week())
    aggregate = _week()
    plain = _build(aggregate)
    compensated = _build(
        SettlementAggregate(**{**aggregate.__dict__, "payout_other": Decimal("40000")})
    )

    assert compensated.wb_commission == plain.wb_commission
    assert compensated.payout_for_goods == plain.payout_for_goods + Decimal("40000")
    assert with_compensation.compensations == Decimal(0)


def test_separately_billed_acquiring_never_reduces_the_payout() -> None:
    """«Комиссия за организацию платежа» is a memo, not a withholding.

    WB does not deduct it from ``ppvz_for_pay`` — on the rows that carry it, the
    payout identity's residual equals ``acquiring_fee`` to the kopeck. Treat it
    as withheld and the statement overstates acquiring by exactly that amount
    while understating the commission by the same.
    """
    aggregate = SettlementAggregate(
        **{**_week().__dict__, "acquiring_billed_apart": Decimal("23456.78")}
    )

    statement = _build(aggregate)

    assert statement.acquiring_billed_apart == Decimal("23456.78")
    assert statement.payout_total == EXPECTED_PAYOUT_TOTAL
    assert statement.total_withheld == _build(_week()).total_withheld


def test_cost_coverage_is_reported_beside_the_margin() -> None:
    """A margin computed over part of the units says so, in the same object.

    A seller rarely has a cost on file for every SKU that sells — here 420 of
    the week's 1 050 net units are costed. A margin quoted without that share
    reads as the business's margin and is not.
    """
    statement = _build(_week(), cogs=Decimal("273000.00"), cogs_units=420)

    assert statement.cogs_units == 420
    assert statement.net_units == 1050
    assert statement.cogs_coverage_pct == Decimal("40.00")
    assert statement.margin_profit == EXPECTED_PAYOUT_TOTAL - Decimal("273000.00")


def test_a_refund_only_period_yields_negative_units_and_cogs() -> None:
    """Net units may go negative, and COGS must follow rather than clamp.

    Refund-only report×SKU cells do occur: a week in which a SKU's only rows are
    returns. Flooring COGS at zero there would report the refunded week as pure
    profit.
    """
    aggregate = SettlementAggregate(
        **{
            **_week().__dict__,
            "sold_units": 0,
            "returned_units": 2,
            "sales_gross": Decimal(0),
            "payout_sales": Decimal(0),
        }
    )

    statement = _build(aggregate, cogs=Decimal("-1300"), cogs_units=-2)

    assert statement.net_units == -2
    assert statement.cogs == Decimal("-1300")
    assert statement.margin_profit > statement.payout_total


def test_an_empty_period_does_not_divide_by_zero() -> None:
    """A window with no settlements returns zeros and ``None`` ratios, not an error."""
    empty = SettlementAggregate(
        key=None,
        label="",
        date_from=None,
        date_to=None,
        currency="",
        subject_name="",
        brand_name="",
        sold_units=0,
        returned_units=0,
        **{
            name: Decimal(0)
            for name in (
                "sales_gross",
                "returns_gross",
                "sales_before_spp",
                "returns_before_spp",
                "payout_sales",
                "payout_returns",
                "payout_other",
                "wb_commission_reported",
                "wb_commission_vat",
                "wb_reward",
                "acquiring_withheld",
                "acquiring_billed_apart",
                "agency_vat",
                "logistics_forward",
                "logistics_return",
                "logistics_unlegged",
                "storage",
                "acceptance",
                "penalties",
                "deductions",
                "additional_payments",
                "rebill_logistic_cost",
                "advertising",
            )
        },
        rows=0,
    )

    statement = _build(empty)

    assert statement.payout_total == Decimal(0)
    assert statement.average_cheque is None
    assert statement.return_rate_pct is None
    assert statement.margin_pct is None


@pytest.mark.parametrize(
    ("field", "delta"),
    [
        ("logistics_forward", Decimal("1250")),
        ("storage", Decimal("1250")),
        ("acceptance", Decimal("1250")),
        ("penalties", Decimal("1250")),
        ("deductions", Decimal("1250")),
        ("rebill_logistic_cost", Decimal("1250")),
    ],
)
def test_every_withholding_reduces_the_bottom_line(field: str, delta: Decimal) -> None:
    """Each withheld charge lowers «итого к оплате» by its own amount.

    Guards against a charge landing in the statement's structure but not in its
    total — the failure mode where a new WB fee is displayed and ignored.
    """
    baseline = _build(_week())

    heavier = _build(
        SettlementAggregate(**{**_week().__dict__, field: getattr(_week(), field) + delta})
    )

    assert heavier.payout_total == baseline.payout_total - delta


def test_additional_payments_raise_the_bottom_line() -> None:
    """«Доплаты» are money in, so they add to «итого к оплате».

    Practically never non-zero in settlement data, which is exactly why the sign
    needs pinning: nothing in the data would reveal it flipped.
    """
    baseline = _build(_week())

    with_payment = _build(
        SettlementAggregate(**{**_week().__dict__, "additional_payments": Decimal("1250")})
    )

    assert with_payment.payout_total == baseline.payout_total + Decimal("1250")


def test_agency_vat_is_reported_but_never_deducted() -> None:
    """Agent's VAT («НДС агента») is a memo figure — «итого к оплате» is invariant to it.

    540 000.00 KGS this week, 18 % of gross sales. It sits outside the
    settlement identity, which closes without it; subtracting it anywhere would
    understate the payout by that much.
    """
    baseline = _build(_week())

    doubled = _build(
        SettlementAggregate(**{**_week().__dict__, "agency_vat": Decimal("1080000.00")})
    )

    assert doubled.agency_vat == Decimal("1080000.00")
    assert doubled.payout_total == baseline.payout_total
    assert doubled.margin_profit == baseline.margin_profit
