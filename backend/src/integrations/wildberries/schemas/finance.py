"""Raw payload model for the WB Finance realization report.

Finance — realization report: ``GET /api/v5/supplier/reportDetailByPeriod``.

Verified live shape (2026-07-22, KGS account): a flat list of settlement rows,
one per ``rrd_id``. Only the fields the ``finreports`` module persists are
``supplier_oper_name == "Штраф"`` + ``bonus_type_name == "Занижение фактических
``delivery_rub`` billed on WB's inflated volume.
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

    supplier_oper_name: str = ""
    bonus_type_name: str = ""
    gi_box_type_name: str = ""
    delivery_method: str = ""
    currency_name: str = ""

    rr_dt: date | None = None
    order_dt: datetime | None = None
    sale_dt: datetime | None = None
    fix_tariff_date_from: datetime | None = None
    fix_tariff_date_to: datetime | None = None

    quantity: int = 0
    delivery_amount: int = 0
    dlv_prc: Decimal | None = None
    delivery_rub: Decimal = Field(default=Decimal(0))
    penalty: Decimal = Field(default=Decimal(0))
    additional_payment: Decimal = Field(default=Decimal(0))
    rebill_logistic_cost: Decimal = Field(default=Decimal(0))
    storage_fee: Decimal = Field(default=Decimal(0))
    acceptance: Decimal = Field(default=Decimal(0))
    deduction: Decimal = Field(default=Decimal(0))
