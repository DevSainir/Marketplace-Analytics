"""Warehouse mark model — the «Отгрузить» flag on a warehouse for one SKU.

Managers mark the warehouses they ship a SKU to; the stock table then sorts
marked warehouses ahead of unmarked ones. A mark is scoped to the SKU: marking
«Тула» for one nm_id says nothing about «Тула» on any other SKU, so the natural
key is the ``(nm_id, warehouse_name)`` pair (composite-key precedent:
:class:`~src.modules.monitoring.models.matrix_override.MatrixOverride`).

Presence of a row == the warehouse is marked; unmarking deletes the row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class WarehouseMark(Base):
    """One marked («на отгрузку») warehouse of one SKU.

    Attributes:
        nm_id: WB SKU identifier the mark belongs to.
        warehouse_name: WB warehouse name exactly as reported by the
            stocks-report API (matches ``StockSnapshot.warehouse_name``).
        created_at: When the warehouse was marked.
    """

    __tablename__ = "warehouse_mark"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    warehouse_name: Mapped[str] = mapped_column(String(128), primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
