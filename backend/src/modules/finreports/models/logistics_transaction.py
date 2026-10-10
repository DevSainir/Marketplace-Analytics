"""Settlement-row model — one line of the WB weekly realization report.

One row per WB ``rrd_id`` — from ``reportDetailByPeriod`` until 2026-09-22, from
finance-api ``sales-reports/detailed`` since, weekly and provisional daily
reports alike (the weekly one re-keys a daily row's ``report_id``). Stores the WB-authored
facts **verbatim** (money, counts, dates, operation/reason classifiers, join
a later baseline, tariff or cost-price correction re-prices history without a
data migration.

This one table backs both of the module's outputs:

* **The P&L.** Revenue (``retail_amount``), WB's cut (``ppvz_vw`` +
  ``ppvz_vw_nds``), acquiring, and the payout (``ppvz_for_pay``) come off the
  «Продажа»/«Возврат» rows; logistics, storage, acceptance, penalties and
  deductions off their own operations. Nothing in the statement is sourced from
  anywhere but these columns and the seller's own cost prices.
  ``supplier_oper_name == "Штраф"`` + ``bonus_type_name == "Занижение фактических
  ``delivery_rub`` billed on WB's inflated volume is the larger silent

The table keeps its historical name; it long predates the P&L and renaming it
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.modules.finreports.constants import LOGISTICS_OPER, SALE_OPERS

_SCHEMA: str = "finreports"


class LogisticsTransaction(Base):
    """One settlement operation from the WB realization report (raw facts).

    Attributes:
        rrd_id: WB report-row id (natural primary key).
        report_id: Owning ``realizationreport_id``.
        workspace_id: Owning workspace (tenancy).
        nm_id / barcode / sa_name / ts_name: Product identity (``sa_name`` is
            served lower-case by WB — stored as received; normalise on join).
        srid / shk_id / gi_id: WB operation / shipment / goods-income join keys.
        office_name: The warehouse/office the row was priced at.
        subject_name / brand_name: Catalogue identity WB puts on the row itself.
        rr_dt / order_dt / sale_dt: Settlement, order and sale dates.
        supplier_oper_name: Operation kind (Логистика/Продажа/Штраф/…).
        doc_type_name: Продажа vs Возврат on the money rows.
        gi_box_type_name / delivery_method / site_country / srv_dbs: Supply,
            delivery and settlement-scheme descriptors.
        currency_name: Row settlement currency (e.g. ``KGS``).
        quantity: Units on the row.
        delivery_amount / return_amount: **Counts, not money.** Exactly one of
            them is 1 on a «Логистика» row, which is what splits ``delivery_rub``
            into логистика к клиенту and обратная логистика.
        retail_price / retail_price_withdisc_rub / retail_amount: Card price,
            price after the seller's discount, and what the buyer actually paid.
        sale_percent / commission_percent / ppvz_spp_prc / ppvz_kvw_prc_base /
            ppvz_kvw_prc / acquiring_percent: The percentages WB applied.
        ppvz_for_pay: К перечислению for the row — the settled bottom line, and
            the anchor of the payout identity ``ppvz_for_pay = retail_amount -
            ppvz_vw - ppvz_vw_nds - acquiring_fee - ppvz_reward``.
        ppvz_vw / ppvz_vw_nds / ppvz_sales_commission / ppvz_reward: WB's reward
            net of VAT, the VAT on it, the pre-поверенный figure, and the
            поверенный's own reward.
        acquiring_fee / acquiring_bank / payment_processing: Payment costs.
        product_discount_for_report / supplier_promo / seller_promo_discount /
            loyalty_discount / installment_cofinancing_amount / cashback_*:
            Who funded the gap between card price and what was paid.
        agency_vat: НДС агента — reported alongside, not part of the payout.
        dlv_prc: Delivery coefficient applied to the row.
        penalty / additional_payment / rebill_logistic_cost / storage_fee /
            acceptance / deduction: The row's other money fields.
        fix_tariff_date_from / fix_tariff_date_to: The tariff window WB locked.
        created_at: Row insertion timestamp.
    """

    __tablename__ = "logistics_transaction"
    __table_args__ = (
        Index("ix_logistics_txn_nm_id_rr_dt", "nm_id", "rr_dt"),
        Index("ix_logistics_txn_ws_rr_dt", "workspace_id", "rr_dt"),
        Index("ix_logistics_txn_oper", "supplier_oper_name"),
        # Two PARTIAL indexes, both for the per-article P&L. Each covers a
        # query whose rows are a small fraction of the table, and each carries
        # what that query reads in INCLUDE so it never touches the table:
        # fines are 6 104 rows of 1 459 394, sales 444 920. Measured, they take
        # the page's two remaining detail scans from ~4 s each to ~0.3 s.
        Index(
            "ix_logistics_txn_penalty",
            "workspace_id",
            "rr_dt",
            postgresql_include=["nm_id", "bonus_type_name", "penalty"],
            postgresql_where=text("penalty <> 0"),
        ),
        # The predicate is WB's own operation name, and
        # `tests/unit/finreports/test_pnl_indexes.py` fails if SALE_OPERS ever
        # stops matching it — a rename would leave this index unusable and the
        # page silently slow again.
        Index(
            "ix_logistics_txn_sale",
            "workspace_id",
            "rr_dt",
            postgresql_include=["retail_amount"],
            postgresql_where=text(
                "supplier_oper_name IN ({})".format(", ".join(f"'{oper}'" for oper in SALE_OPERS))
            ),
        ),
        # 1.6 GB heap: 26 k pages read off disk, 8.9 s, the largest part of a
        # whole-history recompute (measured 2026-10-10). Everything it reads is
        # in the index. The predicate is checked against LOGISTICS_OPER by the
        # same test as the sale index.
        Index(
            "workspace_id",
            "nm_id",
            "rr_dt",
            postgresql_include=["delivery_rub"],
            postgresql_where=text(f"supplier_oper_name = '{LOGISTICS_OPER}'"),
        ),
        {"schema": _SCHEMA},
    )

    rrd_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    sa_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    ts_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    srid: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    shk_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gi_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    office_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    subject_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    brand_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    rr_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    sale_dt: Mapped[date | None] = mapped_column(Date, nullable=True)

    supplier_oper_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    doc_type_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    bonus_type_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    gi_box_type_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    delivery_method: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    currency_name: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    site_country: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    srv_dbs: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Counts, never money — exactly one of the two is 1 on a «Логистика» row,
    # which is what splits ``delivery_rub`` into forward and return logistics.
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivery_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    return_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Revenue side.
    retail_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    retail_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    retail_price_withdisc_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    sale_percent: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0), nullable=False)
    commission_percent: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal(0), nullable=False
    )

    # WB's cut and the settled payout.
    ppvz_for_pay: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    # NOT Numeric(14, 2). WB derives this by dividing a VAT-inclusive reward by
    # 1.12 and publishes the quotient unrounded (~14 decimals), so rounding it to
    # kopecks makes it bit-identical to ``ppvz_sales_commission`` and breaks the
    # payout identity on ~2 % of rows — measured: 30 of 1 792 in one week. Ten
    # decimals is far below the identity's 0.005 tolerance and keeps that check
    # usable as a data-truth test.
    ppvz_vw: Mapped[Decimal] = mapped_column(Numeric(18, 10), default=Decimal(0), nullable=False)
    ppvz_vw_nds: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    ppvz_sales_commission: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    ppvz_reward: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    ppvz_spp_prc: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0), nullable=False)
    ppvz_kvw_prc_base: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal(0), nullable=False
    )
    ppvz_kvw_prc: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0), nullable=False)
    acquiring_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    acquiring_percent: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal(0), nullable=False
    )
    acquiring_bank: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    payment_processing: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    # Discounts — who funded the gap between card price and what was paid.
    product_discount_for_report: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    supplier_promo: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    seller_promo_discount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    loyalty_discount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    installment_cofinancing_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    cashback_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    cashback_discount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    cashback_commission_change: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    agency_vat: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)

    # Charges withheld from the payout.
    dlv_prc: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    delivery_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    penalty: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    additional_payment: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    rebill_logistic_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    storage_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    acceptance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)

    fix_tariff_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    fix_tariff_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
