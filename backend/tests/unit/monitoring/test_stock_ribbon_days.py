"""Unit tests for the "Stock by warehouse" ribbon's day list.

The ribbon renders one column group per day and scrolls sideways through the
window, so the rule that matters is which DAYS come back — a day WB never
reported must still be a column (empty), and a window longer than the ribbon
serves must be cut from the old end, never the new one.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.monitoring.constants import MAX_STOCK_RANGE_DAYS
from src.modules.monitoring.services.analytics.stock_view import StockViewAnalytics

NM_ID = 111


class _Row:
    """Stand-in for a ``StockSnapshot`` ORM row."""

    def __init__(self, stat_date: date, chrt_id: int, warehouse_name: str, quantity: int) -> None:
        self.stat_date = stat_date
        self.chrt_id = chrt_id
        self.warehouse_name = warehouse_name
        self.region_name = "Central"
        self.quantity = quantity
        self.in_way_to_client = 0
        self.in_way_from_client = 0


class _FakeStockRepo:
    """In-memory stand-in for ``StockRepository``."""

    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows
        self.asked: tuple[date, date] | None = None

    async def list_for_sku_window(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[_Row]:
        self.asked = (date_from, date_to)
        return [row for row in self.rows if date_from <= row.stat_date <= date_to]


class _FakeSizeRepo:
    """In-memory stand-in for ``ProductSizeRepository``."""

    async def get_labels_by_chrt_ids(self, chrt_ids: set[int]) -> dict[int, str]:
        return dict.fromkeys(chrt_ids, "S")


def _service(rows: list[_Row]) -> tuple[StockViewAnalytics, _FakeStockRepo]:
    stocks = _FakeStockRepo(rows)
    service = StockViewAnalytics(stock_repo=stocks, product_size_repo=_FakeSizeRepo())  # type: ignore[arg-type]
    return service, stocks


async def test_an_unreported_day_is_an_empty_column_not_a_gap() -> None:
    """A day WB never sent must still hold its place in the ribbon.

    Dropping it would slide every older day one column to the right, and the
    reader would compare two days that are not next to each other.
    """
    observed = date(2026, 7, 3)
    service, _ = _service([_Row(observed, chrt_id=1, warehouse_name="Kazan", quantity=7)])

    result = await service.get_stock_range(
        nm_id=NM_ID, date_from=date(2026, 7, 1), date_to=date(2026, 7, 3)
    )

    assert [day.stat_date for day in result.days] == [
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    ]
    assert [day.stock.total_quantity for day in result.days] == [0, 0, 7]


async def test_every_day_carries_its_own_snapshot() -> None:
    """One query for the window, split back out by day — not carried over."""
    service, _ = _service(
        [
            _Row(date(2026, 7, 1), chrt_id=1, warehouse_name="Kazan", quantity=5),
            _Row(date(2026, 7, 2), chrt_id=1, warehouse_name="Kazan", quantity=2),
        ]
    )

    result = await service.get_stock_range(
        nm_id=NM_ID, date_from=date(2026, 7, 1), date_to=date(2026, 7, 2)
    )

    assert [day.stock.total_quantity for day in result.days] == [5, 2]
    assert [cell.warehouse_name for cell in result.days[0].stock.cells] == ["Kazan"]


async def test_a_window_past_the_cap_keeps_its_newest_days() -> None:
    """The ribbon opens on today, so the old end is the end to drop."""
    end = date(2026, 7, 31)
    service, stocks = _service([])

    result = await service.get_stock_range(
        nm_id=NM_ID, date_from=end - timedelta(days=200), date_to=end
    )

    assert len(result.days) == MAX_STOCK_RANGE_DAYS
    assert result.days[-1].stat_date == end
    assert stocks.asked == (end - timedelta(days=MAX_STOCK_RANGE_DAYS - 1), end)
