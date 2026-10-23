"""Response DTOs for the per-SKU P&L report (the "By SKU" view).

One row per SKU over an arbitrary settlement-date window, mirroring the
industry-standard per-SKU sheet: units and orders, revenue and SPP,
logistics, penalties by category, advertising, the payout and the net profit.

Three columns come from outside the settlement report, and each declares it:

* **Orders** — the settlement only records buyouts; orders come from the
  sales-funnel history (``None`` when the window predates it).
* **Advertising** — the settlement bills advertising as account-level invoices with
  no SKU; the per-SKU spend comes from the Promotion API statistics (``None``
  when the window predates them).
* **Cost price** — the seller's own figure (``None`` when not on file, and
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


class SkuExclusionInput(BaseModel):
    """Request body for marking a SKU "Exclude from total" (or clearing it)."""

    excluded: bool


class PnlSkuRow(BaseModel):
    """One SKU's slice of the window, every money figure in the row currency.

    Percentages are shares of :attr:`revenue_paid` (net sales minus returns),
    matching the reference workbook's convention.
    """

    nm_id: int
    sa_name: str
    #: The card's main image on WB's public CDN, or ``None`` when the monitoring
    #: catalogue holds none for this SKU — including on the totals and
    #: account-level rows, which are not a product. A direct https link: the
    #: browser fetches it from WB, not from us.
    photo_url: str | None = None
    #: WB's catalogue identity for the SKU (category / brand). "" on the
    #: totals and account-level bucket rows, which span many subjects/brands.
    subject_name: str
    brand_name: str

    #: Whether the seller marked this SKU "Exclude from total". Never true
    #: for the account-level bucket. The mark is persisted per workspace and is
    #: what the dashboard's exclusion-aware figures are computed against.
    is_excluded: bool

    #: Ordered units from the funnel history; ``None`` = no funnel coverage.
    orders_units: int | None
    sold_units: int
    returned_units: int
    return_rate_pct: Decimal | None
    #: The inputs of WB's buyout rate, from the funnel by ORDER date: buyouts and
    #: decided deliveries (buyouts + refusals) of the orders placed in the
    #: window. ``None`` without funnel coverage. Kept beside the percentage so a
    #: sum of rows can be re-divided rather than averaged.
    buyout_units: int | None
    decided_units: int | None
    #: Buyout rate = buyout_units / decided_units — the figure WB's seller portal shows.
    #: ``None`` when no order in the window has been decided yet. The size
    #: cut measures its own buyout differently (sold / delivered, by
    #: settlement date): the funnel carries no size. docs/finreports/PNL.md.
    buyout_pct: Decimal | None

    #: Sales / returns, in the settlement currency (what buyers paid on sale / refund rows).
    sales_amount: Decimal
    returns_amount: Decimal
    #: Sales minus returns — the base every percentage in the row is against, and
    #: the sales figure actually shown (net of returns, to match WB's finance page).
    revenue_paid: Decimal
    #: The same net revenue at the seller's own pre-SPP price.
    revenue_seller_price: Decimal
    spp_amount: Decimal
    spp_pct: Decimal | None
    #: Average receipt — net revenue per bought-out unit. ``None`` when net units 0.
    average_cheque: Decimal | None

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

    #: Promotion-API spend, GROSS of who funded it; ``None`` = the window has
    #: no advertising coverage. Left gross on purpose — it is what WB's own
    #: seller portal shows, and the bonus below is what turns it into money spent.
    advertising: Decimal | None
    advertising_pct: Decimal | None

    #: Bonuses — the share of :attr:`advertising` WB paid out of its own bonus
    #: pool (cashback), as a POSITIVE magnitude to be SUBTRACTED.
    #:
    #: Positive, not negative, because every money field on this row is a
    #: positive magnitude whose sign is applied where it is composed — the same
    #: rule that keeps WB's positively-served returns from being added to sales.
    #: The screen renders it negative and green; the arithmetic subtracts it
    #: exactly once, in :attr:`advertising_cash`.
    #:
    #: ``None`` when the write-off ledger has no coverage for the window, which
    #: is NOT the same as zero: "we do not know" and "there were no bonuses" read
    #: differently on a report, and only the second one may lower a cost.
    ad_bonus: Decimal | None
    #: advertising - ad_bonus: what the advertising actually cost the seller.
    #: This — never :attr:`advertising` — is what profit and ROI use.
    advertising_cash: Decimal | None

    #: Payout for goods — Σ ``ppvz_for_pay``, WB's settled payout.
    payout_for_goods: Decimal
    #: Payout — the payout net of this SKU's own withholdings
    #: (its logistics, penalties and the rare SKU-attributed storage).
    payout_net: Decimal

    #: payout_net - cogs - advertising_cash. ``None`` when cogs is unknown — a
    #: profit computed against free goods is worse than no figure.
    net_profit: Decimal | None
    net_profit_pct: Decimal | None

    #: ROI = net profit / cost * 100. ``None`` without cost (profit is ``None``
    #: then too) or when cost is zero.
    roi_pct: Decimal | None


class PnlDashboard(BaseModel):
    """The dashboard KPIs — exclusion-aware, computed on the backend.

    Separate from :attr:`PnlSkuReportResponse.totals` on purpose. ``totals`` is
    the full reconciled window (Σ rows + unallocated, to the kopeck — a tested
    invariant). This is what the five cards show, and its four per-SKU figures
    drop the SKUs the seller marked "Exclude from total". Account-level
    money (other deductions) has no SKU, so it is never affected by a mark.
    """

    #: Sales — at the SELLER's price (WB's retail price net of the agreed
    #: discount, i.e. before WB's SPP), net of returns, over non-excluded SKUs.
    #: This is what the seller is effectively paid on (WB funds the SPP gap).
    sales: Decimal
    #: Customer price — the same net revenue at the after-SPP price the buyer
    #: actually paid; WB's own sale figure. The page switches between the two.
    paid: Decimal
    #: Units on sale rows (gross) and on refund rows; the card shows the
    #: difference, so its count is net like its money.
    sold_units: int
    returned_units: int
    return_rate_pct: Decimal | None
    #: Logistics over non-excluded SKUs, and its share of :attr:`sales`.
    logistics: Decimal
    logistics_pct: Decimal | None
    #: Cost price of the non-excluded costed SKUs; SKUs with sales but no
    #: cost on file are counted in :attr:`uncosted_count`, not summed here.
    cogs: Decimal
    uncosted_count: int
    #: Payout — Σ non-excluded SKUs' payout + the account-level bucket.
    payout_net: Decimal
    #: Other deductions — Σ ``deduction`` (WB's own line), account-level, so it
    #: is exclusion-independent. ``advertising`` is its "WB Promotion" share.
    other_deductions: Decimal
    advertising: Decimal
    #: How many SKUs are currently marked out of the count.
    excluded_count: int


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
    #: The whole window in one row — the full reconciled total (all SKUs).
    totals: PnlSkuRow
    #: The exclusion-aware KPIs the five dashboard cards render.
    dashboard: PnlDashboard
    notes: list[str]
