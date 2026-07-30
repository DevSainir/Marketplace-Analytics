"""Response DTOs for the per-SKU P&L report (the «По артикулам» view).

One row per SKU over an arbitrary settlement-date window, mirroring the
industry-standard «По артикулам» sheet: units and orders, revenue and СПП,
logistics, penalties by category, advertising, the payout and the net profit.

Three columns come from outside the settlement report, and each declares it:

* **Заказы** — the settlement only records buyouts; orders come from the
  sales-funnel history (``None`` when the window predates it).
* **Реклама** — the settlement bills advertising as account-level invoices with
  no SKU; the per-SKU spend comes from the Promotion API statistics (``None``
  when the window predates them).
* **Себестоимость** — the seller's own figure (``None`` when not on file, and
  then the profit is ``None`` too rather than a number that pretends the goods
  were free).

Money that WB does not attribute to any SKU (account-level storage, acceptance,
subscriptions, the advertising invoices themselves) is NOT smeared across rows —
it lands in ``unallocated``, so Σ rows + unallocated reconciles exactly to the
window statement while every per-SKU figure stays traceable to that SKU's rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SkuPenalty(BaseModel):
    """One penalty category on one SKU, named by WB's own reason string."""

    reason: str
    amount: Decimal


class PnlSkuRow(BaseModel):
    """One SKU's slice of the window, every money figure in the row currency.

    Percentages are shares of :attr:`revenue_paid` (net «Продажи - Возвраты»),
    matching the reference workbook's convention.
    """

    nm_id: int
    sa_name: str

    #: Ordered units from the funnel history; ``None`` = no funnel coverage.
    orders_units: int | None
    sold_units: int
    returned_units: int
    return_rate_pct: Decimal | None

    #: Продажи / Возвраты, сом (what buyers paid on sale / refund rows).
    sales_amount: Decimal
    returns_amount: Decimal
    #: Продажи - Возвраты — the base every percentage in the row is against.
    revenue_paid: Decimal
    #: The same net revenue at the seller's own pre-СПП price.
    revenue_seller_price: Decimal
    spp_amount: Decimal
    spp_pct: Decimal | None

    logistics_forward: Decimal
    logistics_return: Decimal
    logistics_total: Decimal
    logistics_pct: Decimal | None

    penalties_total: Decimal
    penalties: list[SkuPenalty]

    #: Cost per unit as entered by the seller; ``None`` = not on file.
    cost_price: Decimal | None
    #: cost_price x net units; ``None`` when no cost is on file.
    cogs: Decimal | None

    #: Promotion-API spend; ``None`` = the window has no advertising coverage.
    advertising: Decimal | None
    advertising_pct: Decimal | None

    #: К перечислению за товар — Σ ``ppvz_for_pay``, WB's settled payout.
    payout_for_goods: Decimal
    #: К перечислению — the payout net of this SKU's own withholdings
    #: (its logistics, penalties and the rare SKU-attributed storage).
    payout_net: Decimal

    #: payout_net - cogs - advertising. ``None`` when cogs is unknown — a profit
    #: computed against free goods is worse than no figure.
    net_profit: Decimal | None
    net_profit_pct: Decimal | None


class PnlSkuReportResponse(BaseModel):
    """The per-SKU report plus its reconciliation frame."""

    date_from: date
    date_to: date
    currency: str
    #: Real SKUs, largest net revenue first.
    rows: list[PnlSkuRow]
    #: Account-level money WB attributes to no SKU. ``None`` when the window has
    #: none. Σ rows + unallocated = totals, exactly.
    unallocated: PnlSkuRow | None
    #: The whole window in one row — the dashboard reads from here.
    totals: PnlSkuRow
    notes: list[str]
