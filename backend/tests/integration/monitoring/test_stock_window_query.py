"""The ribbon's window query, against a real database.

The "Stock by warehouse" ribbon asks for a month of snapshots in ONE query and
splits them by day in Python, so the ordering the service relies on has to come
out of SQL rather than out of a comparison it forgot to write: days ascending,
and within a day the warehouse/size order every column group repeats.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos.stocks import StockRepository

_NM_ID = 995716075
_OTHER_SKU = 953770957


async def _snapshots(session: AsyncSession) -> None:
    """Three days for one SKU, plus a neighbour's row on the middle day."""
    session.add_all(
        [
            StockSnapshot(
                stat_date=date(2026, 8, 12),
                nm_id=_NM_ID,
                warehouse_name="Tula",
                chrt_id=965033858,
                quantity=4,
            ),
            StockSnapshot(
                stat_date=date(2026, 8, 13),
                nm_id=_NM_ID,
                warehouse_name="Krasnodar",
                chrt_id=965033858,
                quantity=15,
            ),
            StockSnapshot(
                stat_date=date(2026, 8, 13),
                nm_id=_NM_ID,
                warehouse_name="Kazan",
                chrt_id=965033858,
                quantity=9,
            ),
            StockSnapshot(
                stat_date=date(2026, 8, 14),
                nm_id=_OTHER_SKU,
                warehouse_name="Tula",
                chrt_id=737265999,
                quantity=99,
            ),
        ]
    )
    await session.flush()


async def test_the_window_comes_back_day_by_day_in_order(db_session: AsyncSession) -> None:
    """Ascending by day, then by warehouse — the order the ribbon renders in."""
    await _snapshots(db_session)
    repo = StockRepository(db_session)

    rows = await repo.list_for_sku_window(
        nm_id=_NM_ID, date_from=date(2026, 8, 12), date_to=date(2026, 8, 14)
    )

    assert [(row.stat_date, row.warehouse_name) for row in rows] == [
        (date(2026, 8, 12), "Tula"),
        (date(2026, 8, 13), "Kazan"),
        (date(2026, 8, 13), "Krasnodar"),
    ]


async def test_the_window_is_inclusive_at_both_ends(db_session: AsyncSession) -> None:
    """A day on the boundary belongs to the window, and a day outside does not."""
    await _snapshots(db_session)
    repo = StockRepository(db_session)

    rows = await repo.list_for_sku_window(
        nm_id=_NM_ID, date_from=date(2026, 8, 13), date_to=date(2026, 8, 13)
    )

    assert {row.stat_date for row in rows} == {date(2026, 8, 13)}
