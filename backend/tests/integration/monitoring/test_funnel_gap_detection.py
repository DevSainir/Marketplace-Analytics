"""Which funnel days count as a hole the nightly pass has to fill.

07.09.2026 fell between the backfill lane and the nightly cohort pass and kept
no WB order sums for three days with every run green. The survey that now runs
after the pass must see such a day — and must not see the idle rows WB's
aggregate never completes (no orders, no cohort, for good), or the alarm would
burn forever.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import SalesFunnelDaily
from src.modules.monitoring.repos import FunnelRepository

SOLD, IDLE = 7101, 7102
WINDOW = {"since": date(2026, 9, 1), "through": date(2026, 9, 30)}


def _row(
    nm_id: int, day: date, *, orders: int, cancel: int | None, order_sum: str | None
) -> SalesFunnelDaily:
    return SalesFunnelDaily(
        stat_date=day,
        nm_id=nm_id,
        open_count=orders * 10,
        cart_count=orders * 2,
        order_count=orders,
        buyout_count=0,
        cancel_count=cancel,
        add_to_wishlist=0,
        cart_conversion=0,
        order_conversion=0,
        buyout_conversion=0,
        order_sum=None if order_sum is None else Decimal(order_sum),
        currency="" if order_sum is None else "KGS",
    )


async def test_a_day_an_article_sold_on_without_wbs_sum_is_a_hole(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            _row(SOLD, date(2026, 9, 6), orders=3, cancel=1, order_sum="900"),
            _row(SOLD, date(2026, 9, 7), orders=3, cancel=1, order_sum=None),
        ]
    )
    await db_session.flush()

    days = await FunnelRepository(db_session).incomplete_days(nm_ids=[SOLD, IDLE], **WINDOW)

    assert days == [date(2026, 9, 7)]


async def test_a_day_with_orders_and_no_cohort_is_a_hole(db_session: AsyncSession) -> None:
    db_session.add(_row(SOLD, date(2026, 9, 8), orders=2, cancel=None, order_sum="600"))
    await db_session.flush()

    days = await FunnelRepository(db_session).incomplete_days(nm_ids=[SOLD], **WINDOW)

    assert days == [date(2026, 9, 8)]


async def test_an_idle_row_wb_never_completes_is_not_a_hole(db_session: AsyncSession) -> None:
    """WB's aggregate omits articles with no activity; their cohort stays empty for good."""
    db_session.add(_row(IDLE, date(2026, 9, 9), orders=0, cancel=None, order_sum=None))
    await db_session.flush()

    days = await FunnelRepository(db_session).incomplete_days(nm_ids=[IDLE], **WINDOW)

    assert days == []
