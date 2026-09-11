"""Pinned SKU model — the global «Закрепить» flag on a SKU.

Managers pin the SKUs the whole team is watching; pins are GLOBAL (shared by
every account), so the row carries no user reference — the natural key is the
``nm_id`` itself. Presence of a row == the SKU is pinned; unpinning deletes
the row.

The manual chip order and the chip highlight colour are global for the same
reason: the row is one shared watchlist, so a reorder or a repaint by one
manager is what every teammate sees.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class PinnedSku(Base):
    """One globally pinned SKU.

    Attributes:
        nm_id: WB SKU identifier that is pinned.
        sort_order: Manual position in the chip row (ascending). A fresh pin
            lands after every existing one; drag-and-drop rewrites the column.
            Not unique — workspaces reorder only their own subset of this
            global table, so two workspaces' positions may coincide.
        color: Chip background tint as ``#rrggbb``, or ``None`` for the default
            unpainted chip.
        created_at: When the SKU was pinned — breaks ``sort_order`` ties.
    """

    __tablename__ = "pinned_sku"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
