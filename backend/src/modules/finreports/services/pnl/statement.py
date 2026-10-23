"""Pure composition of one settlement aggregate into a P&L statement.

No I/O, no session — aggregates and cost prices in, a
:class:`~src.modules.finreports.schemas.pnl.PnlStatement` out. That is what lets
the whole statement be unit-tested against a full WB week without a database.

**The commission line is a residual, and that is deliberate.** WB publishes its
reward twice: ``ppvz_vw`` unrounded and ``ppvz_sales_commission`` rounded to
kopecks. Adding either to ``ppvz_vw_nds`` gives a commission that misses the
authoritative payout by ~0.12 KGS a week, so a reader adding up the printed
lines would not arrive at the payout. Deriving it instead as

    revenue_paid - payout_for_goods - acquiring_withheld - wb_reward

makes the block close to the penny against ``ppvz_for_pay``, which is the one
figure WB actually settles on and which is never recomputed here. The reported
``ppvz_vw`` sums are carried through the aggregate purely to cross-check it.

That only works because the acquiring term is the *withheld* part. WB labels some
``acquiring_fee`` rows as the payment-arrangement fee incl. VAT and bills them
separately rather than deducting them — thousands of rows over a seller's
history. Feeding the undifferentiated ``acquiring_fee`` into the
residual would move exactly that much out of "WB commission" and into "Acquiring" —
a plausible-looking statement with two wrong lines that still totals correctly.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.schemas.pnl import PnlSection, PnlStatement, ReasonShare

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` if undefined."""
    if whole == _ZERO:
        return None
    return (part / whole * _HUNDRED).quantize(Decimal("0.01"))


def _section(
    label: str, amount: Decimal, revenue: Decimal, reasons: list[ReasonShare]
) -> PnlSection:
    """Wrap one charge as a statement section with its share and drill-down."""
    return PnlSection(
        label=label, amount=amount, share_pct=_pct(amount, revenue), breakdown=reasons
    )


def build_statement(
    aggregate: SettlementAggregate,
    *,
    key: str | None,
    label: str,
    cogs: Decimal,
    cogs_units: int,
    logistics_reasons: list[ReasonShare],
    storage_reasons: list[ReasonShare],
    penalty_reasons: list[ReasonShare],
    deduction_reasons: list[ReasonShare],
) -> PnlStatement:
    """Compose one statement from its aggregate and the costs that apply to it.

    Args:
        aggregate: The summed settlement inputs for this bucket.
        key: Bucket identity (report id, month, ``nm_id``) or ``None`` for a total.
        label: Human-readable bucket name.
        cogs: Cost of the units this bucket settled, for the SKUs that have one.
        cogs_units: Net units that cost actually covers.
        logistics_reasons / storage_reasons / penalty_reasons / deduction_reasons:
            WB's own ``bonus_type_name`` splits for the charge lines. Empty for a
            period or SKU bucket — the drill-downs are built once for the whole
            window, since a per-bucket split is four more queries per row.

    Returns:
        The statement, with every share and margin already computed.
    """
    revenue_paid = aggregate.sales_gross - aggregate.returns_gross
    revenue_seller = aggregate.sales_before_spp - aggregate.returns_before_spp
    payout_from_sales = aggregate.payout_sales - aggregate.payout_returns
    payout_goods = payout_from_sales + aggregate.payout_other
    logistics = (
        aggregate.logistics_forward + aggregate.logistics_return + aggregate.logistics_unlegged
    )

    # Derived, not summed — see the module docstring. Against the SALE-side
    # payout only: WB's standalone compensations also land in ``ppvz_for_pay``,
    # and folding them in would report them as negative commission. On this
    # seller's 2025 that alone would have shifted the line by 160 280 KGS.
    commission_total = (
        revenue_paid - payout_from_sales - aggregate.acquiring_withheld - aggregate.wb_reward
    )

    withheld = (
        logistics
        + aggregate.storage
        + aggregate.acceptance
        + aggregate.penalties
        + aggregate.deductions
        + aggregate.rebill_logistic_cost
        - aggregate.additional_payments
    )
    payout_total = payout_goods - withheld
    net_units = aggregate.sold_units - aggregate.returned_units

    return PnlStatement(
        key=key,
        label=label,
        date_from=aggregate.date_from,
        date_to=aggregate.date_to,
        currency=aggregate.currency,
        sold_units=aggregate.sold_units,
        returned_units=aggregate.returned_units,
        net_units=net_units,
        return_rate_pct=_pct(Decimal(aggregate.returned_units), Decimal(aggregate.sold_units)),
        revenue_seller_price=revenue_seller,
        wb_discount=revenue_seller - revenue_paid,
        revenue_paid=revenue_paid,
        average_cheque=(revenue_paid / net_units).quantize(Decimal("0.01")) if net_units else None,
        wb_commission=commission_total,
        wb_commission_vat=aggregate.wb_commission_vat,
        wb_reward=aggregate.wb_reward,
        acquiring=aggregate.acquiring_withheld,
        acquiring_billed_apart=aggregate.acquiring_billed_apart,
        compensations=aggregate.payout_other,
        payout_from_sales=payout_from_sales,
        payout_for_goods=payout_goods,
        logistics=_section("Logistics", logistics, revenue_seller, logistics_reasons),
        logistics_forward=aggregate.logistics_forward,
        logistics_return=aggregate.logistics_return,
        logistics_unlegged=aggregate.logistics_unlegged,
        storage=_section("Storage", aggregate.storage, revenue_seller, storage_reasons),
        acceptance=aggregate.acceptance,
        penalties=_section("Penalties", aggregate.penalties, revenue_seller, penalty_reasons),
        deductions=_section("Deductions", aggregate.deductions, revenue_seller, deduction_reasons),
        advertising=aggregate.advertising,
        additional_payments=aggregate.additional_payments,
        rebill_logistic_cost=aggregate.rebill_logistic_cost,
        total_withheld=withheld,
        payout_total=payout_total,
        cogs=cogs,
        cogs_units=cogs_units,
        cogs_coverage_pct=_pct(Decimal(cogs_units), Decimal(net_units)) if net_units else None,
        gross_profit=revenue_paid - cogs,
        margin_profit=payout_total - cogs,
        margin_pct=_pct(payout_total - cogs, revenue_seller),
        agency_vat=aggregate.agency_vat,
        settlement_rows=aggregate.rows,
    )
