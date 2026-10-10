"""Data access for per-day SKU action rows («Действия» under the matrix).

Sole owner of SQL for ``monitoring.sku_day_action`` and its append-only
``sku_day_action_history`` — services depend on this repository and never
issue queries themselves. One row per SKU-day that has at
least one answered field; the service deletes a row whose every answer is
cleared, so an untouched day is simply absent from
:meth:`SkuDayActionRepository.map_for_window`. All writes are idempotent.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.day_action_history import SkuDayActionHistory
from src.modules.monitoring.models.day_actions import SkuDayAction


class SkuDayActionRepository:
    """Reads and writes the per-day action rows of one SKU."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def map_for_window(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> dict[date, SkuDayAction]:
        """Return the SKU's action rows in the window, keyed by day.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            ``{day: row}`` for the days that carry a row (others are absent).
        """
        stmt = select(SkuDayAction).where(
            SkuDayAction.nm_id == nm_id,
            SkuDayAction.action_date >= date_from,
            SkuDayAction.action_date <= date_to,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.action_date: row for row in rows}

    async def get(self, *, nm_id: int, action_date: date) -> SkuDayAction | None:
        """Return one day's action row, or ``None`` when the day has none.

        Args:
            nm_id: WB SKU identifier.
            action_date: The day to read.

        Returns:
            The stored row, or ``None``.
        """
        stmt = select(SkuDayAction).where(
            SkuDayAction.nm_id == nm_id,
            SkuDayAction.action_date == action_date,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def set(
        self,
        *,
        nm_id: int,
        action_date: date,
        first_rk_type: str | None,
        first_rk_budget: float | None,
        second_rk_type: str | None,
        second_rk_budget: float | None,
        price_change: str | None,
        price_change_amount: float | None,
    ) -> None:
        """Upsert one day's full action state (last write wins).

        Args:
            nm_id: WB SKU identifier.
            action_date: The day the actions describe.
            first_rk_type: «Первая РК» campaign type, or ``None``.
            first_rk_budget: First campaign budget in rubles, or ``None``.
            second_rk_type: «Вторая РК» campaign type, or ``None``.
            second_rk_budget: Second campaign budget in rubles, or ``None``.
            price_change: ``"up"``/``"down"``, or ``None``.
            price_change_amount: Price difference in rubles, or ``None``.
        """
        values = {
            "first_rk_type": first_rk_type,
            "first_rk_budget": first_rk_budget,
            "second_rk_type": second_rk_type,
            "second_rk_budget": second_rk_budget,
            "price_change": price_change,
            "price_change_amount": price_change_amount,
        }
        stmt = (
            pg_insert(SkuDayAction)
            .values(nm_id=nm_id, action_date=action_date, **values)
            .on_conflict_do_update(
                index_elements=[SkuDayAction.nm_id, SkuDayAction.action_date],
                set_={**values, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the write before the request-level commit.
        await self._session.flush()

    async def clear(self, *, nm_id: int, action_date: date) -> None:
        """Delete one day's action row (no-op when the day has none).

        Args:
            nm_id: WB SKU identifier.
            action_date: The day to clear.
        """
        stmt = delete(SkuDayAction).where(
            SkuDayAction.nm_id == nm_id,
            SkuDayAction.action_date == action_date,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def record_change(
        self,
        *,
        nm_id: int,
        action_date: date,
        changed_by: uuid.UUID,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        """Append one change to the day's history (never updated or deleted).

        Args:
            nm_id: WB SKU identifier.
            action_date: The day the change was saved to.
            changed_by: The account that saved it.
            before: The answers before the save, ``None`` for a new day.
            after: The answers after the save, ``None`` for a cleared day.
        """
        self._session.add(
            SkuDayActionHistory(
                nm_id=nm_id,
                action_date=action_date,
                changed_by=changed_by,
                before=before,
                after=after,
            )
        )
        await self._session.flush()
