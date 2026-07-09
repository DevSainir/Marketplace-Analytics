"""Remaining-stock snapshot time-series model.

One row per ``(date, nm_id, warehouse_name, chrt_id)`` — stock is tracked at the
**size** grain (``chrt_id`` is WB's size characteristic id) within each
warehouse. Daily stock snapshots feed the Out-of-Stock (OOS) masking step of the
baseline-demand pipeline (which sums quantity across sizes/warehouses per day).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class StockSnapshot(Base):
    """Daily remaining-stock quantity for one SKU size at one warehouse.

    Sourced from ``POST /api/analytics/v1/stocks-report/wb-warehouses``.

    Attributes:
        stat_date: Snapshot calendar day (Moscow time).
        nm_id: WB SKU identifier.
        warehouse_name: Regional warehouse the quantity refers to.
        chrt_id: WB size characteristic id (identifies the specific size).
        region_name: Warehouse region (denormalized for convenient grouping).
        quantity: Remaining units in stock for this size at this warehouse.
        in_way_to_client: Units in transit to customers.
        in_way_from_client: Units in transit back from customers (returns).
    """

    __tablename__ = "stock_snapshot"
    __table_args__ = (
        # Per-SKU reads (nm_id + date range) cannot use the stat_date-led PK.
        Index("ix_stock_snapshot_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    warehouse_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    chrt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    region_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_way_to_client: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_way_from_client: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
