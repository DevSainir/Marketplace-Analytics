"""SKU day-action model — the manager's per-day action log under the matrix.

One row per ``(nm_id, action_date)`` recording what was DONE that day (as
opposed to the free-text :class:`~src.modules.monitoring.models.
sku_day_comment.SkuDayComment` note): whether the unified / manual advertising
campaigns were switched on (and with what budget), and whether the price was
changed (direction + size). Actions are GLOBAL (shared by every account) —
same convention as pins/marks/comments, so the row carries no user reference.

Every field is nullable: an unanswered question simply stays ``NULL``. A row
where every answer is ``NULL`` is deleted rather than stored.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SkuDayAction(Base):
    """One SKU-day's logged manager actions.

    Attributes:
        nm_id: WB SKU identifier the actions are attached to.
        action_date: The day the actions describe (a matrix column).
        uni_rk_enabled: «Включали РК единая?» — ``True``/``False``, ``None``
            when unanswered.
        uni_rk_budget: The unified campaign's «Бюджет рекламы», rubles.
        manual_rk_enabled: «Включали РК ручная?» — same convention.
        manual_rk_budget: The manual campaign's «Бюджет рекламы», rubles.
        price_change: «Меняли цену?» — ``"up"`` (повысили), ``"down"``
            (понизили), ``"none"`` (нет), or ``None`` when unanswered.
        price_change_amount: «На сколько» — the price difference, rubles.
        updated_at: When the row was last edited (bumped on every save).
    """

    __tablename__ = "sku_day_action"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    action_date: Mapped[date] = mapped_column(Date, primary_key=True)

    uni_rk_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uni_rk_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    manual_rk_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    manual_rk_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    price_change: Mapped[str | None] = mapped_column(String(8), nullable=True)
    price_change_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
