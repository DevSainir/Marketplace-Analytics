"""SKU day-action history — every change ever saved to an "Actions" row.

:class:`~src.modules.monitoring.models.day_actions.SkuDayAction` holds only the
LAST state of a day (the frontend PUTs the whole day, last write wins), so on
its own it cannot answer "who changed this, and what was there before". That
question came up on 2026-10-10: two SKUs' answers for 09.10 had been saved on
11.09, and the only evidence was request paths in the logs — the values that
11.09 held before were recoverable from a backup and nowhere else.

One append-only row per save that changed something. It carries no foreign key
to the action row or to the user, on purpose: the record must outlive a cleared
day and a deleted account. Like the action rows it has no tenant column — it is
scoped through ``nm_id``, and only the ``WorkspaceSku``-guarded PUT writes it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "monitoring"


class SkuDayActionHistory(Base):
    """One saved change of one SKU-day's "Actions" answers.

    Attributes:
        id: UUIDv7, so rows sort by time even within one ``changed_at`` tick.
        nm_id: WB SKU identifier the change was made on.
        action_date: The day (matrix column) the change was saved to.
        changed_by: The account that saved it (soft reference — no FK, so the
            row survives the account being deleted).
        changed_at: When the change was saved.
        before: The day's answers before the save, ``None`` when it had none.
        after: The answers after the save, ``None`` when the save cleared them.
    """

    __tablename__ = "sku_day_action_history"
    __table_args__ = (
        Index("ix_sku_day_action_history_sku_day", "nm_id", "action_date"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action_date: Mapped[date] = mapped_column(Date, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
