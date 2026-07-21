"""Per-day stock breakdowns and the «Отгрузить» warehouse marks."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.repos import (
    ProductSizeRepository,
    StockRepository,
    WarehouseMarkRepository,
)
from src.modules.monitoring.schemas import StockDayResponse, WarehouseMarksResponse
from src.modules.monitoring.services.analytics.presenters import build_stock_detail


class StockViewAnalytics:
    """Serves exact-day stock breakdowns and manages warehouse marks."""

    def __init__(
        self,
        *,
        stock_repo: StockRepository,
        product_size_repo: ProductSizeRepository,
        warehouse_mark_repo: WarehouseMarkRepository,
    ) -> None:
        """Inject the stock, size-label, and mark repositories."""
        self._stocks = stock_repo
        self._product_sizes = product_size_repo
        self._warehouse_marks = warehouse_mark_repo

    async def get_stock_day(self, *, nm_id: int, on_date: date) -> StockDayResponse:
        """Return one exact snapshot day's size x warehouse stock breakdown.

        Feeds one side of the two-day stock comparison. A day without a
        snapshot returns an empty breakdown (snapshots are never carried onto
        neighbouring days — an unobserved day must not fake data).

        Args:
            nm_id: WB SKU identifier.
            on_date: The exact snapshot day to fetch.

        Returns:
            The day's :class:`StockDayResponse`.
        """
        rows = await self._stocks.list_for_sku_day(nm_id=nm_id, stat_date=on_date)
        size_labels = await self._product_sizes.get_labels_by_chrt_ids(
            {row.chrt_id for row in rows}
        )
        marked_warehouses = await self._warehouse_marks.list_names(nm_id=nm_id)
        return StockDayResponse(
            stat_date=on_date,
            stock=build_stock_detail(rows, size_labels, marked_warehouses),
        )

    async def set_warehouse_mark(
        self, *, nm_id: int, warehouse_name: str, marked: bool
    ) -> WarehouseMarksResponse:
        """Set or clear the «Отгрузить» mark on one warehouse of one SKU.

        Marks are per-SKU: marking a warehouse for one nm_id never affects any
        other SKU. Both directions are idempotent.

        Args:
            nm_id: WB SKU identifier.
            warehouse_name: WB warehouse name as reported by the stocks report.
            marked: ``True`` to mark, ``False`` to unmark.

        Returns:
            The SKU's marked warehouse names after the update.
        """
        if marked:
            await self._warehouse_marks.add(nm_id=nm_id, warehouse_name=warehouse_name)
        else:
            await self._warehouse_marks.remove(nm_id=nm_id, warehouse_name=warehouse_name)
        return WarehouseMarksResponse(
            marked_warehouses=await self._warehouse_marks.list_names(nm_id=nm_id)
        )
