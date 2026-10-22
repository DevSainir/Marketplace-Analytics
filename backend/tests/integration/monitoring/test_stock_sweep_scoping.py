"""The stock sweep's warehouse scoping, against a real database.

The daily snapshot is rewritten by deleting the harvested SKUs' rows and
re-inserting what WB served, because WB omits rows that fell to zero. That was
safe while one source fed the table. FBO and FBS now arrive from two different
WB surfaces that fail independently, so an unscoped sweep after a failed FBS
read would delete the seller's warehouse rows and re-insert nothing — showing a
warehouse full of stock as emptied overnight.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos.stocks import StockRepository

_DAY = date(2026, 8, 13)
_NM_ID = 995716075
_FBS = "Moscow (Vnukovo) (FBS)"


async def _snapshot(session: AsyncSession) -> None:
    """Two warehouses' rows for one SKU on one day: one FBO, one FBS."""
    session.add_all(
        [
            StockSnapshot(
                stat_date=_DAY,
                nm_id=_NM_ID,
                warehouse_name="Краснодар",
                chrt_id=965033858,
                quantity=15,
            ),
            StockSnapshot(
                stat_date=_DAY,
                nm_id=_NM_ID,
                warehouse_name=_FBS,
                chrt_id=965033858,
                quantity=1716,
            ),
        ]
    )
    await session.flush()


async def _remaining(session: AsyncSession) -> dict[str, int]:
    """Surviving ``{warehouse: quantity}`` rows for the seeded SKU and day."""
    result = await session.execute(
        sa.select(StockSnapshot.warehouse_name, StockSnapshot.quantity).where(
            StockSnapshot.stat_date == _DAY, StockSnapshot.nm_id == _NM_ID
        )
    )
    return dict(result.all())  # type: ignore[arg-type]


async def test_the_sweep_clears_every_warehouse_by_default(db_session: AsyncSession) -> None:
    """With both sources healthy the day is rewritten wholesale, as before."""
    await _snapshot(db_session)
    repo = StockRepository(db_session)

    deleted = await repo.delete_snapshot_day(snapshot_date=_DAY, nm_ids=[_NM_ID])

    assert deleted == 2
    assert await _remaining(db_session) == {}


async def test_a_spared_warehouse_survives_the_sweep(db_session: AsyncSession) -> None:
    """A failed FBS read leaves the seller's warehouse holding its last figures.

    Stale-but-true beats freshly-wrong: the alternative is reporting a stocked
    warehouse as zero because one of two WB surfaces was unreachable.
    """
    await _snapshot(db_session)
    repo = StockRepository(db_session)

    deleted = await repo.delete_snapshot_day(
        snapshot_date=_DAY, nm_ids=[_NM_ID], keep_warehouses=[_FBS]
    )

    assert deleted == 1
    assert await _remaining(db_session) == {_FBS: 1716}
