"""SKU day-note model — the free-text note attached to one SKU's one day.

Notes are GLOBAL (shared by every account), the same convention as
:class:`~src.modules.monitoring.models.pinned_skus.PinnedSku`: the natural key
is ``(nm_id, comment_date)`` itself, so the row carries no user reference.

A day's note has TWO independent fields, and they behave differently:

* ``body`` — the free-text comment. Purely per-day: what is written on one day
  stays on that day.
* ``header`` — a short title above it. Also stored per day, but it is COPIED
  onto each new day at the day boundary (see the ``monitoring.carry_day_headers``
  task) so a running title continues without being retyped. Because the carry
  materializes a real row, editing or clearing any day's header afterwards
  affects that day alone — nothing is inherited live.

One row per day that has either field; clearing both deletes the row.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SkuDayComment(Base):
    """One SKU-day's note: a free-text comment and its header.

    Attributes:
        nm_id: WB SKU identifier the note is attached to.
        comment_date: The day the note describes (a matrix column).
        body: The comment text (``""`` when the day has only a header).
        header: The note's title (``""`` when the day has only a comment).
            Carried onto the next day when a new day starts.
        updated_at: When the note was last edited (bumped on every save).
    """

    __tablename__ = "sku_day_comment"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    comment_date: Mapped[date] = mapped_column(Date, primary_key=True)

    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    header: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
