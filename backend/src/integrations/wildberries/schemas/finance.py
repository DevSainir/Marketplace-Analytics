"""Raw payload model for the WB Finance realization report.

Finance — realization report: ``GET /api/v5/supplier/reportDetailByPeriod``.

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

from pydantic import Field, field_validator

from src.integrations.wildberries.schemas.base import RawBase


class WBReportDetailRow(RawBase):
    """One settlement operation from ``reportDetailByPeriod`` (raw)."""

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
