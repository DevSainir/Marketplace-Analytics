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


class SkuExclusionInput(BaseModel):
    """Request body for marking a SKU «Не включать в общий счёт» (or clearing it)."""

    excluded: bool


class PnlSkuRow(BaseModel):
    """One SKU's slice of the window, every money figure in the row currency.

    Percentages are shares of :attr:`revenue_paid` (net «Продажи - Возвраты»),
    matching the reference workbook's convention.
    """

    nm_id: int
    sa_name: str
    #: The card's main image on WB's public CDN, or ``None`` when the monitoring
    #: catalogue holds none for this SKU — including on the totals and
    #: account-level rows, which are not a product. A direct https link: the
    #: browser fetches it from WB, not from us.
    photo_url: str | None = None
    #: WB's catalogue identity for the SKU (Тип предмета / Бренд). "" on the
    #: totals and account-level bucket rows, which span many subjects/brands.
    subject_name: str
    brand_name: str

    #: Whether the seller marked this SKU «Не включать в общий счёт». Never true
    #: for the account-level bucket. The mark is persisted per workspace and is
    #: what the dashboard's exclusion-aware figures are computed against.
    is_excluded: bool

    #: Ordered units from the funnel history; ``None`` = no funnel coverage.
    orders_units: int | None
    sold_units: int
    returned_units: int
    return_rate_pct: Decimal | None

    #: Продажи / Возвраты, сом (what buyers paid on sale / refund rows).
    sales_amount: Decimal
    returns_amount: Decimal
    #: Продажи - Возвраты — the base every percentage in the row is against, and
    #: the «Продажи» actually shown (net of returns, to match WB's finance page).
    revenue_paid: Decimal
    #: The same net revenue at the seller's own pre-СПП price.
    revenue_seller_price: Decimal
    spp_amount: Decimal
    spp_pct: Decimal | None
    #: Средний чек — net revenue per bought-out unit. ``None`` when net units 0.
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
    #: cabinet shows, and the bonus below is what turns it into money spent.
    advertising: Decimal | None
    advertising_pct: Decimal | None

    #: «Бонусы» — the share of :attr:`advertising` WB paid out of its own bonus
    #: pool («Кэшбэк»), as a POSITIVE magnitude to be SUBTRACTED.
    #:
    #: Positive, not negative, because every money field on this row is a
    #: positive magnitude whose sign is applied where it is composed — the same
    #: rule that keeps WB's positively-served returns from being added to sales.
    #: The screen renders it negative and green; the arithmetic subtracts it
    #: exactly once, in :attr:`advertising_cash`.
    #:
    #: ``None`` when the write-off ledger has no coverage for the window, which
    #: is NOT the same as zero: «мы не знаем» and «бонусов не было» read
    #: differently on a report, and only the second one may lower a cost.
    ad_bonus: Decimal | None
    #: advertising - ad_bonus: what the advertising actually cost the seller.
    #: This — never :attr:`advertising` — is what profit, ROI and ROMI use.
    advertising_cash: Decimal | None

    #: К перечислению за товар — Σ ``ppvz_for_pay``, WB's settled payout.
    payout_for_goods: Decimal
    #: К перечислению — the payout net of this SKU's own withholdings
    #: (its logistics, penalties and the rare SKU-attributed storage).
    payout_net: Decimal

    #: payout_net - cogs - advertising_cash. ``None`` when cogs is unknown — a
    #: profit computed against free goods is worse than no figure.
    net_profit: Decimal | None
    net_profit_pct: Decimal | None

    #: ROI = net profit / cost * 100. ``None`` without cost (profit is ``None``
    #: then too) or when cost is zero.
    roi_pct: Decimal | None
    #: ROMI = net profit / advertising_cash * 100. The denominator is the money
    #: the seller actually put in, so a campaign WB fully funded returns
    #: ``None`` rather than an infinite ROMI.
    romi_pct: Decimal | None


class PnlDashboard(BaseModel):
    """The dashboard KPIs — exclusion-aware, computed on the backend.

    Separate from :attr:`PnlSkuReportResponse.totals` on purpose. ``totals`` is
    the full reconciled window (Σ rows + unallocated, to the kopeck — a tested
    invariant). This is what the five cards show, and its four per-SKU figures
    drop the SKUs the seller marked «Не включать в общий счёт». Account-level
    money («Прочие удержания») has no SKU, so it is never affected by a mark.
    """

    #: «Продажи» — at the SELLER's price («Цена розничная с учётом согласованной
    #: скидки», i.e. before WB's СПП), net of returns, over non-excluded SKUs.
    #: This is what the seller is effectively paid on (WB funds the СПП gap).
    sales: Decimal
    #: «Оплачено покупателями» — the same net revenue at the after-СПП price the
    #: buyer actually paid; shown as the «Продажи» card's qualifier.
    paid: Decimal
    sold_units: int
    return_rate_pct: Decimal | None
    #: «Логистика» over non-excluded SKUs, and its share of :attr:`sales`.
    logistics: Decimal
    logistics_pct: Decimal | None
    #: «Себестоимость» of the non-excluded costed SKUs; SKUs with sales but no
    #: cost on file are counted in :attr:`uncosted_count`, not summed here.
    cogs: Decimal
    uncosted_count: int
    #: «Перечисление» — Σ non-excluded SKUs' payout + the account-level bucket.
    payout_net: Decimal
    #: «Прочие удержания» — Σ ``deduction`` (WB's own line), account-level, so it
    #: is exclusion-independent. ``advertising`` is its ВБ.Продвижение share.
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
