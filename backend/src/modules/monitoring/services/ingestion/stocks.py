"""Ingestion of per-warehouse stock snapshots."""

from __future__ import annotations

from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBStockRow
from src.modules.monitoring.repos import StockRepository

logger = get_logger(__name__)


class StockIngestion:
    """Persists the daily size x warehouse stock snapshot."""

    def __init__(self, stock_repo: StockRepository) -> None:
        """Inject the stock repository used for persistence."""
        self._stocks = stock_repo

    async def ingest_stocks(
        self,
        rows: list[WBStockRow],
        *,
        snapshot_date: date,
        harvested_nm_ids: list[int] | None = None,
        keep_warehouses: tuple[str, ...] = (),
    ) -> int:
        """Persist per-warehouse stock snapshots for a given day.

        Stored at the **size** grain ``(date, nm_id, warehouse, chrt_id)`` so the
        detail view can show which size sits in which warehouse. Rows are
        de-duplicated on that key (last one wins) to avoid an
        ``ON CONFLICT``-target cardinality violation should WB repeat a key.

        WB's report *omits* rows that dropped to zero, so the harvested SKUs'
        rows for the snapshot day are deleted first (same transaction) — a bare
        upsert would leave a stale "5 units" row behind on a same-day
        re-harvest after a sell-out, corrupting the out-of-stock signal.

        Args:
            rows: Raw per-size/per-warehouse stock rows from the analytics
                client.
            snapshot_date: The Moscow-time calendar day the snapshot represents.
            harvested_nm_ids: Every SKU this harvest covered (a superset of the
                SKUs present in ``rows``); defaults to the SKUs in ``rows`` —
                sufficient only when absence-means-zero cleanup is not needed.
            keep_warehouses: Warehouses excluded from the sweep because the
                source that feeds them failed this run. ``rows`` must then carry
                nothing for them; the day keeps its previous values instead of
                being rewritten as empty.

        Returns:
            The number of size x warehouse rows persisted.
        """
        swept_ids = (
            harvested_nm_ids if harvested_nm_ids is not None else [row.nm_id for row in rows]
        )
        deleted = await self._stocks.delete_snapshot_day(
            snapshot_date=snapshot_date, nm_ids=swept_ids, keep_warehouses=keep_warehouses
        )
        if deleted:
            logger.info("Swept %d prior stock rows for %s before refresh.", deleted, snapshot_date)

        deduped: dict[tuple[int, str, int], WBStockRow] = {}
        for row in rows:
            deduped[(row.nm_id, row.warehouse_name, row.chrt_id)] = row

        flattened: list[dict[str, object]] = [
            {
                "stat_date": snapshot_date,
                "nm_id": row.nm_id,
                "warehouse_name": row.warehouse_name,
                "chrt_id": row.chrt_id,
                "region_name": row.region_name,
                "quantity": row.quantity,
                "in_way_to_client": row.in_way_to_client,
                "in_way_from_client": row.in_way_from_client,
            }
            for row in deduped.values()
        ]
        count = await self._stocks.upsert_many(flattened)
        logger.info("Ingested %d stock rows for %s.", count, snapshot_date)
        return count
