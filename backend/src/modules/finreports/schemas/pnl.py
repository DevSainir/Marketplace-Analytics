"""Response DTOs for the profit-and-loss statement.

The statement is a *settlement-basis* P&L: it reports what WildBerries settled in
a window, not what was ordered in it. A sale bought out in June and refunded in
July appears as revenue in June and as a refund in July — 41 % of this seller's
refunds settle in a different weekly report than their sale — and that is the
correct behaviour for a document whose purpose is to reconcile against money that
actually moved.

Every line here except :attr:`PnlStatement.cogs` and what depends on it is
derived from the WB weekly report alone. The cost of goods is the seller's own
input, so it is reported alongside its coverage and never silently averaged over
SKUs that have no cost on file.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PnlSection(BaseModel):
    """One named amount inside a statement block, with its own drill-down."""

    label: str
    amount: Decimal
    #: Share of net revenue, as a percentage. ``None`` when revenue is zero.
    share_pct: Decimal | None = None
    #: WB's own ``bonus_type_name`` split, when the line has one.
    breakdown: list[ReasonShare] = []


class ReasonShare(BaseModel):
    """One WB-authored reason inside a charge line."""

    reason: str
    amount: Decimal
    rows: int


class PnlStatement(BaseModel):
    """The full statement for one window or one grouping bucket.

    The blocks read top to bottom exactly as the numbers compose:
    units → revenue → what WB kept → what WB withheld → payable → cost → profit.
    """

    key: str | None
    label: str
    date_from: date | None
    date_to: date | None
    currency: str

    # --- Units --------------------------------------------------------------
    sold_units: int
    returned_units: int
    net_units: int
    #: Refunded units as a share of units sold.
    return_rate_pct: Decimal | None

    # --- Revenue ------------------------------------------------------------
    #: Σ ``retail_price_withdisc_rub`` net of refunds — the seller's own price.
    revenue_seller_price: Decimal
    #: The gap WB funded out of its own pocket (SPP).
    wb_discount: Decimal
    #: Σ ``retail_amount`` net of refunds — what buyers actually paid.
    revenue_paid: Decimal
    average_cheque: Decimal | None

    # --- What WB kept out of the sale --------------------------------------
    wb_commission: Decimal
    wb_commission_vat: Decimal
    wb_reward: Decimal
    #: The acquiring WB actually deducted from the payout.
    acquiring: Decimal
    #: «Комиссия за организацию платежа с НДС» — acquiring WB bills separately
    #: instead of withholding. A memo figure: it is not in ``payout_for_goods``
    #: and must not be subtracted anywhere on the statement.
    acquiring_billed_apart: Decimal
    #: Σ ``ppvz_for_pay`` on sale rows less refund rows — the settled payout for
    #: goods actually sold, and what the commission line is derived against.
    payout_from_sales: Decimal
    #: WB's standalone compensations and acquiring corrections — money paid to
    #: the seller outside the sale/refund flow, also carried in ``ppvz_for_pay``.
    compensations: Decimal
    #: Σ ``ppvz_for_pay``, netted, including compensations. WB's own authoritative
    #: figure, never recomputed.
    payout_for_goods: Decimal

    # --- What WB withheld afterwards ---------------------------------------
    logistics: PnlSection
    logistics_forward: Decimal
    logistics_return: Decimal
    #: «Коррекция логистики» — logistics money on no leg (WB sets no counter).
    logistics_unlegged: Decimal
    storage: PnlSection
    acceptance: Decimal
    penalties: PnlSection
    deductions: PnlSection
    #: Advertising billed through «ВБ.Продвижение», already inside ``deductions``.
    advertising: Decimal
    additional_payments: Decimal
    rebill_logistic_cost: Decimal
    total_withheld: Decimal

    #: ``payout_for_goods`` less everything withheld — WB's own bottom line.
    payout_total: Decimal

    # --- Below WB's line ----------------------------------------------------
    cogs: Decimal
    #: Net units the COGS actually covers, and the total it was computed over.
    cogs_units: int
    cogs_coverage_pct: Decimal | None
    gross_profit: Decimal
    #: ``payout_total - cogs``. Before taxes, payroll and anything off-platform.
    margin_profit: Decimal
    margin_pct: Decimal | None

    # --- Memo ---------------------------------------------------------------
    #: «НДС агента» (agent's VAT). Reported by WB alongside the settlement but NOT deducted from
    #: it — shown so the figure is not mistaken for a missing cost.
    agency_vat: Decimal
    settlement_rows: int


class PnlResponse(BaseModel):
    """The statement for a window, plus its per-bucket breakdown."""

    date_from: date
    date_to: date
    grouping: str
    total: PnlStatement
    buckets: list[PnlStatement]
    #: Caveats that qualify the figures — unbackfilled columns, uncosted SKUs,
    #: operations the taxonomy does not recognise.
    notes: list[str]


PnlSection.model_rebuild()
