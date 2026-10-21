"""SKU day-action model — the manager's per-day action log under the matrix.

One row per ``(nm_id, action_date)`` recording what was DONE that day (as
opposed to the free-text :class:`~src.modules.monitoring.models.
sku_day_comment.SkuDayComment` note): which advertising campaigns were run (up
to two, each with its budget), and whether the price was moved (direction +
size). Actions are GLOBAL (shared by every account) — same convention as
pins/marks/comments, so the row carries no user reference.

Every field is nullable: an unanswered question simply stays ``NULL``. A row
where every answer is ``NULL`` is deleted rather than stored.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SkuDayAction(Base):
    """One SKU-day's logged manager actions.

    The two ad campaign slots are positional — «Первая РК» / «Вторая РК» — and each holds
    a campaign TYPE (``uni`` / ``manual_search`` / ``manual_shelves`` / ``cpc``)
    rather than a yes/no. The frontend keeps the two types distinct; a stored
    row should never repeat one across the slots.

    Attributes:
        nm_id: WB SKU identifier the actions are attached to.
        action_date: The day the actions describe (a matrix column).
        first_rk_type: «Первая РК» campaign type, or ``None`` when unset.
        first_rk_budget: The first campaign's «Бюджет рекламы», rubles.
        second_rk_type: «Вторая РК» campaign type, or ``None``.
        second_rk_budget: The second campaign's «Бюджет рекламы», rubles.
        price_change: «Меняли цену?» — ``"up"`` (raised) / ``"down"``
            (lowered), or ``None`` when unset.
        price_change_amount: «На сколько» — the price difference, rubles.
        updated_at: When the row was last edited (bumped on every save).
    """

    __tablename__ = "sku_day_action"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    action_date: Mapped[date] = mapped_column(Date, primary_key=True)

    first_rk_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    first_rk_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    second_rk_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    second_rk_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    price_change: Mapped[str | None] = mapped_column(String(8), nullable=True)
    price_change_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
