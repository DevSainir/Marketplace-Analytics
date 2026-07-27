"""Logistics-transaction model — one settlement row of the finance report.

One row per WB ``rrd_id`` from ``reportDetailByPeriod``. Stores the WB-authored
facts **verbatim** (money, dates, operation/reason classifiers, join keys); the
or tariff correction re-prices history without a data migration.

* ``supplier_oper_name == "Штраф"`` + ``bonus_type_name == "Занижение фактических
* ``delivery_rub`` billed on WB's inflated volume → the (larger) silent
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

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
        rr_dt / order_dt / sale_dt: Settlement, order and sale dates.
        supplier_oper_name: Operation kind (Логистика/Продажа/Штраф/…).
        gi_box_type_name / delivery_method: Supply/delivery descriptors.
        currency_name: Row settlement currency (e.g. ``KGS``).
        quantity / delivery_amount: Unit counts.
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

    rr_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    sale_dt: Mapped[date | None] = mapped_column(Date, nullable=True)

    supplier_oper_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    bonus_type_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    gi_box_type_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    delivery_method: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    currency_name: Mapped[str] = mapped_column(String(8), default="", nullable=False)

    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivery_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
