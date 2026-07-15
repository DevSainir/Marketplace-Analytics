"""SKU comment model — a free-text note attached to one SKU.

Comments are GLOBAL (shared by every account), the same convention as
:class:`~src.modules.monitoring.models.pinned_skus.PinnedSku` and
:class:`~src.modules.monitoring.models.warehouse_marks.WarehouseMark`: the
natural key is the ``nm_id`` itself, so the row carries no user reference. One
row per SKU that has a note; clearing the note deletes the row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SkuComment(Base):
    """One SKU's free-text comment.

    Attributes:
        nm_id: WB SKU identifier the comment is attached to.
        body: The note text (never empty — an empty note deletes the row).
        updated_at: When the comment was last edited (bumped on every save).
    """

    __tablename__ = "sku_comment"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    body: Mapped[str] = mapped_column(Text, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
