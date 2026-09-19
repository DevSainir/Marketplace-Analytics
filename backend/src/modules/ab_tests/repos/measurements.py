"""Data access for what a rotation measured: intervals and counter baselines.

Split from :mod:`.variants`, which owns the photos and the log of their turns.
These two tables are the poller's arithmetic — the difference between two
cumulative readings, and the reading it was differenced against — and they move
together on every pass while the variant tables move only when a photo does.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AdCounterSnapshot, VariantStatWindow
from src.modules.ab_tests.services.collection import (
    CampaignDays,
    Counters,
    counters_from_reading,
)
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
        campaign_id: int,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None:
        """Record the traffic one campaign brought over one polling interval.

        Idempotent on ``(variant_id, window_start, campaign_id)``: a pass that
        is retried after a mid-transaction failure must not credit the same
        interval twice, and one interval now writes a row per campaign.

        Args:
            test_id: Owning test.
            variant_id: The photo that was live for the interval.
            campaign_id: The campaign whose counters this delta came from.
            window_start: Previous poll's timestamp.
            window_end: This poll's timestamp.
            counters: Traffic gained over the interval.
        """
        stmt = pg_insert(VariantStatWindow).values(
            test_id=test_id,
            variant_id=variant_id,
            campaign_id=campaign_id,
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
                index_elements=[
                    VariantStatWindow.variant_id,
                    VariantStatWindow.window_start,
                    VariantStatWindow.campaign_id,
                ]
            )
        )
        await self._session.flush()

    async def impressions_for_variant(
        self, *, variant_id: uuid.UUID, since: datetime | None = None
    ) -> int:
        """Impressions credited to one photo, optionally within one turn.

        Summed across campaigns on purpose: the rotation's budget is «сколько
        раз это фото показали», and a card pushed by two campaigns reaches that
        number twice as fast because it really was shown twice as often.

        ``since`` is what makes this a TURN and not a lifetime. The rotation is
        a circle, so a photo comes back round; the budget it has to meet is the
        one for the turn it is serving now. Without the bound, a photo returning
        for its second lap arrived already over budget and was replaced on the
        very next pass — see :mod:`..services.rotation`. A rotation always lands
        on a window boundary (the runner closes the window, moves the baseline,
        then swaps), so ``window_start >= since`` selects exactly the windows of
        the current turn and splits none of them.

        Args:
            variant_id: The photo.
            since: When its current turn began. ``None`` sums every turn, which
                is what the result table wants and the trigger does not.

        Returns:
            Summed views; 0 when the photo has gathered nothing.
        """
        stmt = select(func.coalesce(func.sum(VariantStatWindow.views), 0)).where(
            VariantStatWindow.variant_id == variant_id
        )
        if since is not None:
            stmt = stmt.where(VariantStatWindow.window_start >= since)
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
            every campaign-day of one pass is stamped with the same moment, so
            this is the boundary the next window starts from.
        """
        stmt = select(AdCounterSnapshot).where(AdCounterSnapshot.test_id == test_id)
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            return None
        by_campaign: CampaignDays = {}
        for row in rows:
            by_campaign.setdefault(row.campaign_id, {})[row.stat_date] = counters_from_reading(
                views=row.views,
                clicks=row.clicks,
                atbs=row.atbs,
                orders=row.orders,
                spend=Decimal(row.spend),
            )
        return Snapshot(captured_at=max(row.captured_at for row in rows), by_campaign=by_campaign)

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
        self, *, test_id: uuid.UUID, by_campaign: CampaignDays, captured_at: datetime
    ) -> None:
        """Overwrite the stored reading with this poll's.

        Args:
            test_id: Owning test.
            by_campaign: Cumulative counters per campaign per advertising day.
            captured_at: The moment of this poll.
        """
        payload = [
            {
                "test_id": test_id,
                "campaign_id": campaign_id,
                "stat_date": day,
                "views": counters.views,
                "clicks": counters.clicks,
                "atbs": counters.atbs,
                "orders": counters.orders,
                "spend": counters.spend,
                "captured_at": captured_at,
            }
            for campaign_id, days in by_campaign.items()
            for day, counters in days.items()
        ]
        if not payload:
            return

        stmt = pg_insert(AdCounterSnapshot).values(payload)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    AdCounterSnapshot.test_id,
                    AdCounterSnapshot.campaign_id,
                    AdCounterSnapshot.stat_date,
                ],
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
