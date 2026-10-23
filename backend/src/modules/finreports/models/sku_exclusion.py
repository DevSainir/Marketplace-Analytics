"""Per-SKU "Exclude from total" mark — a seller editorial choice.

The presence of a row *is* the mark: a ``(workspace_id, nm_id)`` here means the
seller has chosen to keep that SKU out of the dashboard's overall total. Clearing
the mark deletes the row. Kept in its own table for the same reason cost prices
are — it is seller-authored, not harvested from WB, and must never be confused
with a settlement fact.

The mark only ever changes what the *dashboard* sums; it never touches the
per-SKU rows or the reconciled ``totals`` (Σ rows + unallocated), so the report
stays auditable against WB while the seller's private overall total is theirs to
shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class PnlSkuExclusion(Base):
    """One SKU the seller marked "Exclude from total", per workspace.

    Attributes:
        workspace_id: Owning workspace (tenancy; part of the natural key, so the
            mark is shared across every user of that workspace and only theirs).
        nm_id: WB SKU identifier the mark applies to.
        created_at: When the SKU was marked — a light audit trail.
    """

    __tablename__ = "pnl_sku_exclusion"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
