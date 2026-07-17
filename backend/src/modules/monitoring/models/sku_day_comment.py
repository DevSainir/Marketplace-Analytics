"""SKU day-comment model — a free-text note attached to one SKU's one day.

Comments are GLOBAL (shared by every account), the same convention as
:class:`~src.modules.monitoring.models.pinned_skus.PinnedSku` and
:class:`~src.modules.monitoring.models.warehouse_marks.WarehouseMark`: the
natural key is ``(nm_id, comment_date)`` itself, so the row carries no user
reference. One row per commented day; clearing the note deletes the row.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SkuDayComment(Base):
    """One SKU-day's free-text comment.

    Attributes:
        nm_id: WB SKU identifier the comment is attached to.
        comment_date: The day the note describes (a matrix column).
        body: The note text (never empty — an empty note deletes the row).
        updated_at: When the comment was last edited (bumped on every save).
    """

    __tablename__ = "sku_day_comment"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    comment_date: Mapped[date] = mapped_column(Date, primary_key=True)

    body: Mapped[str] = mapped_column(Text, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
