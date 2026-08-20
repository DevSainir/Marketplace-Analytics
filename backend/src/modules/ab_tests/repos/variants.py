"""Data access for variant photos, their exposures and their attributed days.

Three small tables that always move together, so they share a file rather than
three near-identical ones. Sole owner of SQL for ``ab_test_variant``,
``ab_test_variant_exposure`` and ``ab_test_variant_stat_daily``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AbTestVariant, VariantExposure, VariantStatDaily
from src.modules.ab_tests.services.attribution import AttributedDay, ExposureWindow


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

    async def windows_for_test(self, *, test_id: uuid.UUID) -> list[ExposureWindow]:
        """Return a test's exposure history as attribution windows.

        Args:
            test_id: Owning test.

        Returns:
            Windows in activation order.
        """
        stmt = (
            select(VariantExposure)
            .where(VariantExposure.test_id == test_id)
            .order_by(VariantExposure.activated_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            ExposureWindow(
                variant_id=row.variant_id,
                activated_at=row.activated_at,
                deactivated_at=row.deactivated_at,
            )
            for row in rows
        ]


class VariantStatRepository:
    """Attributed advertising days, one row per variant per day."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def upsert_days(self, *, test_id: uuid.UUID, days: Sequence[AttributedDay]) -> int:
        """Write attributed days, overwriting any earlier version of the same day.

        WB restates recent advertising days as conversions settle, so a day is
        upserted rather than inserted: the latest reading wins.

        Args:
            test_id: Owning test, denormalised onto every row.
            days: Attributed rows to persist.

        Returns:
            How many rows were written.
        """
        if not days:
            return 0

        payload = [
            {
                "variant_id": day.variant_id,
                "stat_date": day.stat_date,
                "test_id": test_id,
                "views": day.views,
                "clicks": day.clicks,
                "atbs": day.atbs,
                "orders": day.orders,
                "spend": day.spend,
            }
            for day in days
        ]
        stmt = pg_insert(VariantStatDaily).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[VariantStatDaily.variant_id, VariantStatDaily.stat_date],
            set_={
                "views": stmt.excluded.views,
                "clicks": stmt.excluded.clicks,
                "atbs": stmt.excluded.atbs,
                "orders": stmt.excluded.orders,
                "spend": stmt.excluded.spend,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return len(payload)

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int:
        """Return every impression attributed to one photo, across all rounds.

        Args:
            variant_id: The photo.

        Returns:
            Summed views; 0 when the photo has no attributed days.
        """
        stmt = select(func.coalesce(func.sum(VariantStatDaily.views), 0)).where(
            VariantStatDaily.variant_id == variant_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def days_for_test(self, *, test_id: uuid.UUID) -> list[VariantStatDaily]:
        """Return every attributed day of a test.

        Args:
            test_id: Owning test.

        Returns:
            Rows ordered by date, then variant.
        """
        stmt = (
            select(VariantStatDaily)
            .where(VariantStatDaily.test_id == test_id)
            .order_by(VariantStatDaily.stat_date, VariantStatDaily.variant_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def latest_day(self, *, test_id: uuid.UUID) -> date | None:
        """Return the most recent attributed day of a test, if any.

        Args:
            test_id: Owning test.

        Returns:
            The date, or ``None`` when nothing has been attributed yet.
        """
        stmt = select(func.max(VariantStatDaily.stat_date)).where(
            VariantStatDaily.test_id == test_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
