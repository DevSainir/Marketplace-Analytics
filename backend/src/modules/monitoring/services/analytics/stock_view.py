"""Per-day stock breakdowns for the «Остатки по складам» ribbon."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.modules.monitoring.constants import MAX_STOCK_RANGE_DAYS
from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos import ProductSizeRepository, StockRepository
from src.modules.monitoring.schemas import StockDayResponse, StockRangeResponse
from src.modules.monitoring.services.analytics.presenters import build_stock_detail
from src.modules.monitoring.services.analytics.window import resolve_window


class StockViewAnalytics:
    """Serves per-day stock breakdowns."""

    def __init__(
        self,
        *,
        stock_repo: StockRepository,
        product_size_repo: ProductSizeRepository,
    ) -> None:
        """Inject the stock and size-label repositories."""
        self._stocks = stock_repo
        self._product_sizes = product_size_repo

    async def get_stock_range(
        self, *, nm_id: int, date_from: date | None, date_to: date | None
    ) -> StockRangeResponse:
        """Return a size x warehouse breakdown for every day of the window.

        Feeds the «Остатки по складам» ribbon: one column group per day, two
        days on screen, scrolled sideways through the period chosen for the
        whole page. Every calendar day of the window is returned, including
        those WB never reported — an unobserved day is an EMPTY breakdown, not
        a missing entry, because snapshots are never carried onto neighbouring
        days and a silently absent day would read as continuous history.

        Only the most recent :data:`MAX_STOCK_RANGE_DAYS` days of the window are
        served; a full breakdown per day for a whole year is a response nobody
        asked for and a memory cost anyone could ask for.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start (defaults applied by the window
                resolver).
            date_to: Inclusive window end.

        Returns:
            The window's :class:`StockRangeResponse`, oldest day first.
        """
        start, end = resolve_window(date_from, date_to)
        start = max(start, end - timedelta(days=MAX_STOCK_RANGE_DAYS - 1))

        rows = await self._stocks.list_for_sku_window(nm_id=nm_id, date_from=start, date_to=end)
        size_labels = await self._product_sizes.get_labels_by_chrt_ids(
            {row.chrt_id for row in rows}
        )

        by_day: dict[date, list[StockSnapshot]] = defaultdict(list)
        for row in rows:
            by_day[row.stat_date].append(row)

        days = [
            StockDayResponse(
                stat_date=day,
                stock=build_stock_detail(by_day.get(day, []), size_labels),
            )
            for day in _walk_days(start, end)
        ]
        return StockRangeResponse(days=days)


def _walk_days(start: date, end: date) -> list[date]:
    """Return every calendar day from ``start`` to ``end``, inclusive."""
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
