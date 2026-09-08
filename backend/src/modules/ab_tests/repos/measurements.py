"""Data access for what a rotation measured: intervals and counter baselines.

Split from :mod:`.variants`, which owns the photos and the log of their turns.
These two tables are the poller's arithmetic — the difference between two
cumulative readings, and the reading it was differenced against — and they move
together on every pass while the variant tables move only when a photo does.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AdCounterSnapshot, VariantStatWindow
from src.modules.ab_tests.services.collection import Counters, counters_from_reading
from src.modules.ab_tests.services.runner import Snapshot


class WindowRepository:
    """Per-poll traffic, one row per variant per interval."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def append(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None:
        """Record the traffic of one polling interval.

        Idempotent on ``(variant_id, window_start)``: a pass that is retried
        after a mid-transaction failure must not credit the same interval twice.

        Args:
            test_id: Owning test.
            variant_id: The photo that was live for the interval.
            window_start: Previous poll's timestamp.
            window_end: This poll's timestamp.
            counters: Traffic gained over the interval.
        """
        stmt = pg_insert(VariantStatWindow).values(
            test_id=test_id,
            variant_id=variant_id,
            window_start=window_start,
            window_end=window_end,
            views=counters.views,
            clicks=counters.clicks,
            atbs=counters.atbs,
            orders=counters.orders,
            spend=counters.spend,
        )
        await self._session.execute(
            stmt.on_conflict_do_nothing(
                index_elements=[VariantStatWindow.variant_id, VariantStatWindow.window_start]
            )
        )
        await self._session.flush()

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int:
        """Every impression credited to one photo, across all of its turns.

        Args:
            variant_id: The photo.

        Returns:
            Summed views; 0 when the photo has never been live.
        """
        stmt = select(func.coalesce(func.sum(VariantStatWindow.views), 0)).where(
            VariantStatWindow.variant_id == variant_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def windows_for_test(self, *, test_id: uuid.UUID) -> list[VariantStatWindow]:
        """Every recorded interval of a test.

        Args:
            test_id: Owning test.

        Returns:
            Rows ordered by window start.
        """
        stmt = (
            select(VariantStatWindow)
            .where(VariantStatWindow.test_id == test_id)
            .order_by(VariantStatWindow.window_start, VariantStatWindow.variant_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SnapshotRepository:
    """The poller's memory: the last cumulative reading per test per day."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None:
        """Return the stored reading for a test, or ``None`` if never polled.

        Args:
            test_id: Owning test.

        Returns:
            The snapshot, whose ``captured_at`` is the most recent one written —
            every day of one pass is stamped with the same moment, so this is
            the boundary the next window starts from.
        """
        stmt = select(AdCounterSnapshot).where(AdCounterSnapshot.test_id == test_id)
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            return None
        return Snapshot(
            captured_at=max(row.captured_at for row in rows),
            by_day={
                row.stat_date: counters_from_reading(
                    views=row.views,
                    clicks=row.clicks,
                    atbs=row.atbs,
                    orders=row.orders,
                    spend=Decimal(row.spend),
                )
                for row in rows
            },
        )

    async def clear(self, *, test_id: uuid.UUID) -> None:
        """Forget the stored reading, so the next pass starts a fresh baseline.

        Called when a test stops accruing — a pause of either kind. The counters
        WB serves are cumulative since midnight, so a baseline left behind over
        a three-hour pause makes the first window after it three hours wide and
        credits the lot to whichever photo happens to be up. Dropping it puts
        the test back in the state a freshly started one is in: seed, credit
        nothing, carry on from there.

        Args:
            test_id: Owning test.
        """
        await self._session.execute(
            delete(AdCounterSnapshot).where(AdCounterSnapshot.test_id == test_id)
        )
        await self._session.flush()

    async def save(
        self, *, test_id: uuid.UUID, by_day: dict[date, Counters], captured_at: datetime
    ) -> None:
        """Overwrite the stored reading with this poll's.

        Args:
            test_id: Owning test.
            by_day: Cumulative counters per advertising day.
            captured_at: The moment of this poll.
        """
        if not by_day:
            return

        payload = [
            {
                "test_id": test_id,
                "stat_date": day,
                "views": counters.views,
                "clicks": counters.clicks,
                "atbs": counters.atbs,
                "orders": counters.orders,
                "spend": counters.spend,
                "captured_at": captured_at,
            }
            for day, counters in by_day.items()
        ]
        stmt = pg_insert(AdCounterSnapshot).values(payload)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AdCounterSnapshot.test_id, AdCounterSnapshot.stat_date],
                set_={
                    "views": stmt.excluded.views,
                    "clicks": stmt.excluded.clicks,
                    "atbs": stmt.excluded.atbs,
                    "orders": stmt.excluded.orders,
                    "spend": stmt.excluded.spend,
                    "captured_at": stmt.excluded.captured_at,
                },
            )
        )
        await self._session.flush()
