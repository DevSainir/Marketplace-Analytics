"""Repository for :class:`StockSnapshot` rows."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos.base import BaseRepository

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

    async def daily_totals_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> dict[date, int]:
        """Return one SKU's total stock per snapshot day (all sizes/warehouses).

        Feeds the OOS-masking step of the baseline-demand pipeline, which needs
        to know on which days the SKU had zero sellable stock.

        Returns:
            ``{snapshot_day: total_quantity}`` for each day with a snapshot.
        """
        stmt = (
            select(StockSnapshot.stat_date, func.sum(StockSnapshot.quantity).label("quantity"))
            .where(
                StockSnapshot.nm_id == nm_id,
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
            )
            .group_by(StockSnapshot.stat_date)
        )
        result = await self._session.execute(stmt)
        return {row.stat_date: int(row.quantity) for row in result.all()}

    async def latest_totals_by_sku(self, *, date_from: date, date_to: date) -> dict[int, int]:
        """Return each SKU's total stock on its most recent snapshot day.

        Aggregated fully in SQL for the summary listing.

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
