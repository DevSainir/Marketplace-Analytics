"""Per-day stock breakdowns for the two-day comparison view."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.repos import ProductSizeRepository, StockRepository
from src.modules.monitoring.schemas import StockDayResponse
from src.modules.monitoring.services.analytics.presenters import build_stock_detail


class StockViewAnalytics:
    """Serves exact-day stock breakdowns."""

    def __init__(
        self,
        *,
        stock_repo: StockRepository,
        product_size_repo: ProductSizeRepository,
    ) -> None:
        """Inject the stock and size-label repositories."""
        self._stocks = stock_repo
        self._product_sizes = product_size_repo

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
        return StockDayResponse(stat_date=on_date, stock=build_stock_detail(rows, size_labels))
