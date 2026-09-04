"""Data access for variant photos, their exposures, and the polling tables.

Four small tables that always move together, so they share a file rather than
four near-identical ones. Sole owner of SQL for ``ab_test_variant``,
``ab_test_variant_exposure``, ``ab_test_variant_stat_window`` and
``ab_test_ad_snapshot``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import (
    AbTestVariant,
    AdCounterSnapshot,
    VariantExposure,
    VariantStatWindow,
)
from src.modules.ab_tests.services.collection import Counters, counters_from_reading
from src.modules.ab_tests.services.runner import Snapshot


class VariantRepository:
    """Reads and writes the photos in a test's rotation."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def add(
        self,
        *,
        test_id: uuid.UUID,
        image_path: str,
        image_sha256: str,
        content_type: str,
        original_filename: str,
    ) -> AbTestVariant:
        """Append a photo to the end of a test's rotation.

        Args:
            test_id: Owning test.
            image_path: Stored path, relative to the media root.
            image_sha256: Digest of the stored bytes.
            content_type: MIME type as uploaded.
            original_filename: The user's own file name.

        Returns:
            The persisted variant.
        """
        next_position = select(func.coalesce(func.max(AbTestVariant.position) + 1, 1)).where(
            AbTestVariant.test_id == test_id
        )

        variant = AbTestVariant(
            test_id=test_id,
            position=(await self._session.execute(next_position)).scalar_one(),
            image_path=image_path,
            image_sha256=image_sha256,
            content_type=content_type,
            original_filename=original_filename,
        )
        self._session.add(variant)
        await self._session.flush()
        return variant

    async def get(self, *, test_id: uuid.UUID, variant_id: uuid.UUID) -> AbTestVariant | None:
        """Return one variant of a test, or ``None``.

        Args:
            test_id: Owning test — also the tenancy guard, since the caller has
                already resolved the test inside its workspace.
            variant_id: Variant identifier.

        Returns:
            The variant, or ``None``.
        """
        stmt = select(AbTestVariant).where(
            AbTestVariant.id == variant_id, AbTestVariant.test_id == test_id
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

    async def count_for_test(self, *, test_id: uuid.UUID) -> int:
        """Return how many photos a test already carries.

        Args:
            test_id: Owning test.

        Returns:
            The variant count.
        """
        stmt = (
            select(func.count()).select_from(AbTestVariant).where(AbTestVariant.test_id == test_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def delete(self, *, test_id: uuid.UUID, variant_id: uuid.UUID) -> bool:
        """Remove a photo from a test.

        Args:
            test_id: Owning test.
            variant_id: Variant identifier.

        Returns:
            ``True`` when a row was removed.
        """
        stmt = delete(AbTestVariant).where(
            AbTestVariant.id == variant_id, AbTestVariant.test_id == test_id
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return bool(cast("CursorResult[Any]", result).rowcount)


class ExposureRepository:
    """The audit trail of which photo was live when."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def open(
        self, *, test_id: uuid.UUID, variant_id: uuid.UUID, activated_at: datetime
    ) -> VariantExposure:
        """Record that a photo has just gone up.

        Called only after WB accepted the upload, so the table describes what
        happened rather than what was intended.

        Args:
            test_id: Owning test.
            variant_id: The photo now on the card.
            activated_at: When WB accepted it.

        Returns:
            The new exposure row.
        """
        exposure = VariantExposure(
            test_id=test_id, variant_id=variant_id, activated_at=activated_at
        )
        self._session.add(exposure)
        await self._session.flush()
        return exposure

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        """Close whatever exposure is still open for a test.

        Args:
            test_id: Owning test.
            deactivated_at: When the photo came off.
        """
        stmt = select(VariantExposure).where(
            VariantExposure.test_id == test_id, VariantExposure.deactivated_at.is_(None)
        )
        for exposure in (await self._session.execute(stmt)).scalars().all():
            exposure.deactivated_at = deactivated_at
        await self._session.flush()

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None:
        """When the currently installed photo went up.

        This is what the time trigger measures against — the moment WB accepted
        the upload, not the moment the rotation decided to make one.

        Args:
            test_id: Owning test.

        Returns:
            The activation time of the open exposure, or ``None`` when nothing
            is installed.
        """
        stmt = (
            select(VariantExposure.activated_at)
            .where(
                VariantExposure.test_id == test_id,
                VariantExposure.deactivated_at.is_(None),
            )
            .order_by(VariantExposure.activated_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_for_variant(self, *, variant_id: uuid.UUID) -> int:
        """How many separate turns a photo has had.

        Args:
            variant_id: The photo.

        Returns:
            The number of exposures.
        """
        stmt = (
            select(func.count())
            .select_from(VariantExposure)
            .where(VariantExposure.variant_id == variant_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())


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
