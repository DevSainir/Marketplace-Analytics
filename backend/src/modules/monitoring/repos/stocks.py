"""Repository for :class:`StockSnapshot` rows."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos.base import BaseRepository, workspace_sku_select


@dataclass(frozen=True, slots=True)
class StockDailyTotal:
    """One snapshot day's stock totals for a SKU (summed across sizes/warehouses)."""

    stat_date: date
    quantity: int
    in_way_to_client: int
    in_way_from_client: int


_CONFLICT = ("stat_date", "nm_id", "warehouse_name", "chrt_id")
_UPDATE = ("region_name", "quantity", "in_way_to_client", "in_way_from_client")


class StockRepository(BaseRepository):
    """CRUD/read operations for daily per-warehouse stock snapshots."""

    model = StockSnapshot

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of per-warehouse stock rows.

        Args:
            rows: Column->value mappings keyed by ``(stat_date, nm_id,
                warehouse_name)``.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def list_latest_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[StockSnapshot]:
        """Return one SKU's rows for its most recent snapshot day in the window.

        Stock is a point-in-time snapshot, so the detail view only ever renders
        the latest day; filtering in SQL avoids hydrating a year of
        size x warehouse rows to then discard all but one day.
        """
        latest_day = (
            select(func.max(StockSnapshot.stat_date))
            .where(
                StockSnapshot.nm_id == nm_id,
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
            )
            .scalar_subquery()
        )
        stmt = (
            select(StockSnapshot)
            .where(StockSnapshot.nm_id == nm_id, StockSnapshot.stat_date == latest_day)
            .order_by(StockSnapshot.warehouse_name, StockSnapshot.chrt_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_sku_day(self, *, nm_id: int, stat_date: date) -> list[StockSnapshot]:
        """Return one SKU's size x warehouse rows for one exact snapshot day.

        Feeds the two-day stock comparison view: each side of the comparison
        shows the snapshot of its picked day (empty when no snapshot was
        captured that day — days are never carried over).

        Args:
            nm_id: WB SKU identifier.
            stat_date: The exact snapshot day.

        Returns:
            The day's rows, ordered by warehouse then size.
        """
        stmt = (
            select(StockSnapshot)
            .where(StockSnapshot.nm_id == nm_id, StockSnapshot.stat_date == stat_date)
            .order_by(StockSnapshot.warehouse_name, StockSnapshot.chrt_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def daily_totals_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[StockDailyTotal]:
        """Return one SKU's per-day stock totals (all sizes/warehouses summed).

        Feeds the OOS-masking step of the baseline-demand pipeline (quantity)
        and the matrix's per-day stock/in-transit rows (all three sums).

        Returns:
            One :class:`StockDailyTotal` per snapshot day, ascending by date.
        """
        stmt = (
            select(
                StockSnapshot.stat_date,
                func.sum(StockSnapshot.quantity).label("quantity"),
                func.sum(StockSnapshot.in_way_to_client).label("in_way_to_client"),
                func.sum(StockSnapshot.in_way_from_client).label("in_way_from_client"),
            )
            .where(
                StockSnapshot.nm_id == nm_id,
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
            )
            .group_by(StockSnapshot.stat_date)
            .order_by(StockSnapshot.stat_date)
        )
        result = await self._session.execute(stmt)
        return [
            StockDailyTotal(
                stat_date=row.stat_date,
                quantity=int(row.quantity),
                in_way_to_client=int(row.in_way_to_client),
                in_way_from_client=int(row.in_way_from_client),
            )
            for row in result.all()
        ]

    async def latest_totals_by_sku(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> dict[int, int]:
        """Return each SKU's total stock on its most recent snapshot day.

        Aggregated fully in SQL for the summary listing.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            ``{nm_id: latest_total_quantity}`` for every SKU with a snapshot in
            the window.
        """
        latest = (
            select(
                StockSnapshot.nm_id.label("nm_id"),
                func.max(StockSnapshot.stat_date).label("latest_day"),
            )
            .where(
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
                StockSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
            )
            .group_by(StockSnapshot.nm_id)
            .subquery()
        )
        stmt = (
            select(StockSnapshot.nm_id, func.sum(StockSnapshot.quantity).label("quantity"))
            .join(
                latest,
                and_(
                    StockSnapshot.nm_id == latest.c.nm_id,
                    StockSnapshot.stat_date == latest.c.latest_day,
                ),
            )
            .group_by(StockSnapshot.nm_id)
        )
        result = await self._session.execute(stmt)
        return {row.nm_id: int(row.quantity) for row in result.all()}

    async def delete_snapshot_day(self, *, snapshot_date: date, nm_ids: Iterable[int]) -> int:
        """Delete a day's snapshot rows for the given SKUs (pre-refresh sweep).

        WB's stock report simply omits size x warehouse rows that dropped to
        zero, so an upsert alone leaves stale nonzero rows behind on same-day
        re-harvests — silently corrupting the out-of-stock signal. Ingestion
        deletes the harvested SKUs' rows for the snapshot day first (same
        transaction), making the day a faithful mirror of the report.

        Args:
            snapshot_date: The Moscow-time snapshot day being re-written.
            nm_ids: The SKUs covered by this harvest.

        Returns:
            The number of rows deleted.
        """
        ids = list(nm_ids)
        if not ids:
            return 0
        stmt = delete(StockSnapshot).where(
            StockSnapshot.stat_date == snapshot_date,
            StockSnapshot.nm_id.in_(ids),
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)
