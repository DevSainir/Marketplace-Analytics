"""Pinned SKU model — the global «Закрепить» flag on a SKU.

Managers pin the SKUs the whole team is watching; pins are GLOBAL (shared by
every account), so the row carries no user reference — the natural key is the
``nm_id`` itself. Presence of a row == the SKU is pinned; unpinning deletes
the row (same convention as :class:`~src.modules.monitoring.models
.warehouse_marks.WarehouseMark`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class PinnedSku(Base):
    """One globally pinned SKU.

    Attributes:
        nm_id: WB SKU identifier that is pinned.
        created_at: When the SKU was pinned — pins render in pin order.
    """

    __tablename__ = "pinned_sku"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
