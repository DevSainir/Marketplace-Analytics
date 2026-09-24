"""Raw payload model for the WB Finance realization report.

Finance — realization report. Until 2026-09-22 this was
``GET /api/v5/supplier/reportDetailByPeriod``, which :class:`WBReportDetailRow`
still spells; the service now reads ``POST /api/finance/v1/sales-reports/*``
through :class:`WBFinanceReportRow`, which aliases the new names onto the old.

Verified live shape (2026-07-29, KGS account, report 969371534 / 7 097 rows): a
flat list of settlement rows, one per ``rrd_id``. ``RawBase`` ignores whatever WB
adds; everything modelled here is persisted, because this report is the *only*
source the P&L is built from.

Two things this file exists to pin down, both verified by arithmetic against the
live payload rather than taken from WB's documentation:

* **The payout identity.** For every «Продажа»/«Возврат» row,
  ``ppvz_for_pay = retail_amount - ppvz_vw - ppvz_vw_nds - acquiring_fee - ppvz_reward``.
  That is what makes the P&L's «к перечислению» reconcilable line by line instead
  of being a number we assert.
* **``delivery_amount`` and ``return_amount`` are COUNTS, not money.** On a
  «Логистика» row exactly one of them is 1 (5 103 forward vs 3 697 return rows in
  the sample week), which is what splits ``delivery_rub`` into «логистика к
  клиенту» and «обратная логистика». Reading them as ₽ silently doubles logistics.

billed on WB's inflated volume.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import ConfigDict, Field, field_validator

from src.integrations.wildberries.schemas.base import RawBase


def _camel(name: str) -> str:
    """snake_case -> camelCase, which is how the Finance surface spells fields.

    Only used as the DEFAULT alias on :class:`WBFinanceReportRow`; the twenty
    fields WB renamed outright carry an explicit alias that overrides it.
    """
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


class WBReportDetailRow(RawBase):
    """One settlement operation, under the field names ``reportDetailByPeriod`` used (raw).

    Nothing fetches this shape directly since 2026-09-22; it survives as the base
    :class:`WBFinanceReportRow` aliases onto, so every consumer keeps its names.
    """

    @field_validator(
        "rr_dt",
        "order_dt",
        "sale_dt",
        "date_from",
        "date_to",
        "create_dt",
        "fix_tariff_date_from",
        "fix_tariff_date_to",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object | None:
        """Treat WB's empty-string dates (``""``) as ``None``."""
        if value == "":
            return None
        return value

    rrd_id: int
    realizationreport_id: int = 0
    gi_id: int | None = None
    nm_id: int = 0
    barcode: str = ""
    sa_name: str = ""
    ts_name: str = ""
    srid: str = ""
    shk_id: int | None = None
    office_name: str = ""

    # Catalogue identity — WB names the product on the settlement row itself, so
    # a P&L can be grouped by предмет/бренд without joining the content cards.
    subject_name: str = ""
    brand_name: str = ""

    supplier_oper_name: str = ""
    doc_type_name: str = ""
    bonus_type_name: str = ""
    gi_box_type_name: str = ""
    delivery_method: str = ""
    currency_name: str = ""
    site_country: str = ""

    # The report's OWN period, as WB states it. Not derivable from ``rr_dt``:
    # a report can carry no row on its first or last settlement day.
    date_from: date | None = None
    date_to: date | None = None
    create_dt: date | None = None

    rr_dt: date | None = None
    order_dt: datetime | None = None
    sale_dt: datetime | None = None
    fix_tariff_date_from: datetime | None = None
    fix_tariff_date_to: datetime | None = None

    # Counts, not money — see the module docstring.
    quantity: int = 0
    delivery_amount: int = 0
    return_amount: int = 0

    # --- Revenue side -------------------------------------------------------
    #: Price on the card before the seller's own discount.
    retail_price: Decimal = Field(default=Decimal(0))
    #: What the buyer actually paid (``retail_price_withdisc_rub`` less СПП).
    retail_amount: Decimal = Field(default=Decimal(0))
    #: Price after the seller's discount, before WB's own СПП.
    retail_price_withdisc_rub: Decimal = Field(default=Decimal(0))
    sale_percent: Decimal = Field(default=Decimal(0))
    commission_percent: Decimal = Field(default=Decimal(0))

    # --- WB's cut and the payout -------------------------------------------
    #: К перечислению продавцу for this row — the settled bottom line.
    ppvz_for_pay: Decimal = Field(default=Decimal(0))
    #: WB's reward net of VAT (negative when WB co-finances the discount).
    ppvz_vw: Decimal = Field(default=Decimal(0))
    #: VAT charged on that reward.
    ppvz_vw_nds: Decimal = Field(default=Decimal(0))
    #: Reward before the поверенный's services are deducted, when applicable.
    ppvz_sales_commission: Decimal = Field(default=Decimal(0))
    #: Вознаграждение поверенного (ВВ) — zero on this account, kept for parity.
    ppvz_reward: Decimal = Field(default=Decimal(0))
    ppvz_spp_prc: Decimal = Field(default=Decimal(0))
    ppvz_kvw_prc_base: Decimal = Field(default=Decimal(0))
    ppvz_kvw_prc: Decimal = Field(default=Decimal(0))
    acquiring_fee: Decimal = Field(default=Decimal(0))
    acquiring_percent: Decimal = Field(default=Decimal(0))
    acquiring_bank: str = ""
    payment_processing: str = ""

    # --- Discounts WB funds or the seller funds -----------------------------
    product_discount_for_report: Decimal = Field(default=Decimal(0))
    supplier_promo: Decimal = Field(default=Decimal(0))
    seller_promo_discount: Decimal = Field(default=Decimal(0))
    loyalty_discount: Decimal = Field(default=Decimal(0))
    installment_cofinancing_amount: Decimal = Field(default=Decimal(0))
    cashback_amount: Decimal = Field(default=Decimal(0))
    cashback_discount: Decimal = Field(default=Decimal(0))
    cashback_commission_change: Decimal = Field(default=Decimal(0))
    #: НДС агента — reported alongside, NOT part of ``ppvz_for_pay``.
    agency_vat: Decimal = Field(default=Decimal(0))

    # --- Charges withheld from the payout -----------------------------------
    dlv_prc: Decimal | None = None
    delivery_rub: Decimal = Field(default=Decimal(0))
    penalty: Decimal = Field(default=Decimal(0))
    additional_payment: Decimal = Field(default=Decimal(0))
    rebill_logistic_cost: Decimal = Field(default=Decimal(0))
    storage_fee: Decimal = Field(default=Decimal(0))
    acceptance: Decimal = Field(default=Decimal(0))
    deduction: Decimal = Field(default=Decimal(0))

    #: DBS («доставка силами продавца») rows settle differently — kept so the
    #: P&L can tell them apart from ordinary FBO rows if that ever matters.
    srv_dbs: bool = False


class WBFinanceReportRow(WBReportDetailRow):
    """The same settlement row, as the Finance surface spells it.

    `reportDetailByPeriod` was announced for shutdown on 15.07.2026 and is gone
    from WB's documentation; `POST /api/finance/v1/sales-reports/detailed/{id}`
    replaces it at fifteen times the rate. The payload is the same report with
    camelCase names, money as strings, and twenty fields renamed.

    **A subclass, so the field names the rest of the service reads never
    change.** `ingestion/rows.py::settlement_row` maps sixty attributes onto
    `logistics_transaction`, and every column keeps its name; putting the
    translation in aliases here means that function, the model, the
    repositories, the P&L and the claim are untouched by the migration.

    **The renames are NOT derivable from camelCase.** Some `ppvz_` prefixes
    survived (`ppvzReward`, `ppvzSalesCommission`) and some were dropped
    (`vw`, `forPay`), so a converter would silently leave the money columns
    null. Hence a table, and hence
    `docs/finreports/MIGRATION_TO_FINANCE_V1.md` phase 2, which diffs a whole
    report against what we already hold before anything is cut over.

    Three of these are inferences rather than observations, and are what that
    diff is really for: `sellerPromo` is assumed to be the old
    `supplier_promo` (the payload also carries `sellerPromoId` and
    `sellerPromoDiscount`), `sku` the old `barcode`, and `country` the old
    `site_country`.

    Money arriving as a string is an improvement: pydantic parses `"638402.03"`
    to an exact `Decimal`, where a JSON float had to be trusted.
    """

    realizationreport_id: int = Field(default=0, alias="reportId")
    create_dt: date | None = Field(default=None, alias="createDate")
    rr_dt: date | None = Field(default=None, alias="rrDate")
    sa_name: str = Field(default="", alias="vendorCode")
    ts_name: str = Field(default="", alias="techSize")
    barcode: str = Field(default="", alias="sku")
    currency_name: str = Field(default="", alias="currency")
    site_country: str = Field(default="", alias="country")
    supplier_oper_name: str = Field(default="", alias="sellerOperName")
    supplier_promo: Decimal = Field(default=Decimal(0), alias="sellerPromo")
    retail_price_withdisc_rub: Decimal = Field(default=Decimal(0), alias="retailPriceWithDisc")
    delivery_rub: Decimal = Field(default=Decimal(0), alias="deliveryService")
    storage_fee: Decimal = Field(default=Decimal(0), alias="paidStorage")
    acceptance: Decimal = Field(default=Decimal(0), alias="paidAcceptance")
    ppvz_for_pay: Decimal = Field(default=Decimal(0), alias="forPay")
    ppvz_vw: Decimal = Field(default=Decimal(0), alias="vw")
    ppvz_vw_nds: Decimal = Field(default=Decimal(0), alias="vwNds")
    ppvz_spp_prc: Decimal = Field(default=Decimal(0), alias="spp")
    ppvz_kvw_prc_base: Decimal = Field(default=Decimal(0), alias="kvwBase")
    ppvz_kvw_prc: Decimal = Field(default=Decimal(0), alias="kvw")

    #: WB's own name for the product, new on this surface. Today the P&L joins
    #: the content cards for it; nothing reads this yet.
    title: str = ""
    #: The warehouse's logistics coefficient, also new — and directly the
    warehouse_logistics_coeff: Decimal | None = Field(default=None, alias="warehouseLogisticsCoeff")

    model_config = ConfigDict(extra="ignore", populate_by_name=True, alias_generator=_camel)


class WBFinanceReportHeader(RawBase):
    """One report from `POST /api/finance/v1/sales-reports/list`.

    The discovery method the old surface had no equivalent of: it names every
    report WB has formed for the seller, with `createDate` served rather than
    derived from the period arithmetic that
    `src.modules.finreports.services.publication` did until it was deleted on
    2026-09-23.

    It also carries WB's OWN totals for the report. `docs/finreports/PNL.md`
    warns that most ways to get a settlement figure wrong produce a plausible
    statement rather than an error; these sums are the first thing the
    statement can be checked against.
    """

    report_id: int = Field(alias="reportId")
    date_from: date = Field(alias="dateFrom")
    date_to: date = Field(alias="dateTo")
    create_date: date = Field(alias="createDate")
    currency: str = ""
    #: 1 for the weekly realization report. Daily reports exist; what the other
    #: values mean is not yet pinned, so nothing filters on this.
    report_type: int = Field(default=0, alias="reportType")

    retail_amount_sum: Decimal = Field(default=Decimal(0), alias="retailAmountSum")
    for_pay_sum: Decimal = Field(default=Decimal(0), alias="forPaySum")
    delivery_service_sum: Decimal = Field(default=Decimal(0), alias="deliveryServiceSum")
    paid_storage_sum: Decimal = Field(default=Decimal(0), alias="paidStorageSum")
    paid_acceptance_sum: Decimal = Field(default=Decimal(0), alias="paidAcceptanceSum")
    deduction_sum: Decimal = Field(default=Decimal(0), alias="deductionSum")
    penalty_sum: Decimal = Field(default=Decimal(0), alias="penaltySum")
    additional_payment_sum: Decimal = Field(default=Decimal(0), alias="additionalPaymentSum")
    bank_payment_sum: Decimal = Field(default=Decimal(0), alias="bankPaymentSum")
