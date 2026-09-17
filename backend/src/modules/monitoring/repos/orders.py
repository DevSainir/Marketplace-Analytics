"""Repository for :class:`OrderRecord` rows (order-date lines from WB).

Two readers, and they want opposite things. The walk that fills this table asks
«how far have I got», so it reads one timestamp. «Сводка» asks «how many orders
on each day, and what were they worth», which is a grouped read over a кабинет's
SKUs — and the кабинет arrives, as everywhere in ``monitoring``, as a semijoin
through ``product_card``, because an order line carries an ``nm_id`` and WB's
article numbers are global.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import OrderRecord
from src.modules.monitoring.repos.base import BaseRepository, workspace_sku_select

_CONFLICT = ("srid",)
_UPDATE = (
    "nm_id",
    "order_date",
    "is_cancel",
    "price_with_disc",
    "finished_price",
    "last_change_date",
)


@dataclass(frozen=True)
class OrderDayTotal:
    """One day's orders, summed over a кабинет's SKUs.

    Cancellations are excluded from all three figures: a line the customer
    cancelled was never demand, and WB cancels days after the fact — which is
    also why the row stays in the table rather than being deleted.
    """

    order_date: date
    orders: int
    #: Σ the seller's own price, before WB's СПП.
    amount_seller: Decimal
    #: Σ what the customer pays, СПП applied.
    amount_paid: Decimal


class OrderRepository(BaseRepository):
    """Writes the orders walk lands, and the daily series «Сводка» reads."""

    model = OrderRecord

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a page of order lines, keyed by ``srid``.

        Idempotent because it has to be: the feed's ``dateFrom`` bound is
        inclusive, so consecutive pages overlap by whatever shares a timestamp,
        and a cancelled line arrives a second time with ``isCancel`` set.

        Args:
            rows: Column->value mappings keyed by ``srid``.

        Returns:
            How many rows were submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def latest_change(self, *, workspace_id: uuid.UUID) -> datetime | None:
        """The newest ``lastChangeDate`` stored for this кабинет, if any.

        The walk's fallback resume point: a cursor lost to a restart costs one
        re-read of the tail rather than the whole history.
        """
        stmt = select(func.max(OrderRecord.last_change_date)).where(
            OrderRecord.nm_id.in_(workspace_sku_select(workspace_id))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def day_totals(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[OrderDayTotal]:
        """Return one row per day the кабинет was ordered from, ascending.

        Days with no line at all are ABSENT rather than zero — the same rule the
        funnel loader keeps, because a gap in the walk and a day of no demand
        must not look alike.
        """
        stmt = (
            select(
                OrderRecord.order_date,
                func.count(),
                func.coalesce(func.sum(OrderRecord.price_with_disc), 0),
                func.coalesce(func.sum(OrderRecord.finished_price), 0),
            )
            .where(
                OrderRecord.nm_id.in_(workspace_sku_select(workspace_id)),
                OrderRecord.order_date >= date_from,
                OrderRecord.order_date <= date_to,
                OrderRecord.is_cancel.is_(False),
            )
            .group_by(OrderRecord.order_date)
            .order_by(OrderRecord.order_date)
        )
        return [
            OrderDayTotal(
                order_date=row[0],
                orders=int(row[1]),
                amount_seller=Decimal(row[2]),
                amount_paid=Decimal(row[3]),
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def covered_span(self, *, workspace_id: uuid.UUID) -> tuple[date | None, date | None]:
        """``(first, last)`` ordered day on record for this кабинет."""
        stmt = select(func.min(OrderRecord.order_date), func.max(OrderRecord.order_date)).where(
            OrderRecord.nm_id.in_(workspace_sku_select(workspace_id))
        )
        first, last = (await self._session.execute(stmt)).one()
        return first, last
