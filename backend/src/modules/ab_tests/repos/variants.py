"""Data access for the photos in a rotation and the log of their turns.

Sole owner of SQL for ``ab_test_variant`` and ``ab_test_variant_exposure``.
What those turns *measured* lives next door in :mod:`.measurements`: those two
tables move on every polling pass, while these move only when a photo does.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import (
    AbTest,
    AbTestVariant,
    VariantExposure,
)


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
        """Append an uploaded photo to the end of a test's rotation.

        Candidates are numbered from 1. The "Main photo" takes position 0 and
        is written by :meth:`add_original`.

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

    async def add_original(
        self,
        *,
        test_id: uuid.UUID,
        image_path: str,
        image_sha256: str,
        content_type: str,
        original_filename: str,
    ) -> AbTestVariant:
        """Put the "Main photo" at the head of a test's rotation.

        Written at **position 0**, which is why this is a separate method rather
        than an argument to :meth:`add`. Inserting at position 1 would mean
        renumbering every other upload, and ``uq_ab_test_variant_test_position``
        is not deferrable: a single ``SET position = position + 1`` over rows
        1, 2, 3 collides with itself row by row. Position 0 is free by
        construction, so the head of the rotation costs one INSERT and touches
        nothing a running test is already attributing traffic to.

        Uniqueness of the baseline rests on that same constraint: a second
        "Main photo" would be a second row at position 0. The service refuses it
        first, with a message; this is the floor under that check.

        Args:
            test_id: Owning test.
            image_path: Stored path of the uploaded bytes.
            image_sha256: Digest of those bytes.
            content_type: MIME type as uploaded.
            original_filename: The user's own file name.

        Returns:
            The persisted variant.
        """
        variant = AbTestVariant(
            test_id=test_id,
            position=0,
            image_path=image_path,
            image_sha256=image_sha256,
            content_type=content_type,
            original_filename=original_filename,
            is_original=True,
        )
        self._session.add(variant)
        await self._session.flush()
        return variant

    async def get_scoped(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, variant_id: uuid.UUID
    ) -> AbTestVariant | None:
        """Return one variant, checking the workspace in the same query.

        For the image route, which is the one endpoint called once per PHOTO
        rather than once per page. Resolving the test and then the variant costs
        three round trips — the test, its variants through `selectinload`, then
        the variant itself — so a rotation of nine photos spent twenty-seven
        queries proving nine times over that the caller owns the test.

        The tenancy guard is the join predicate rather than a separate read, so
        it is the same rule and not a copy of it: a variant of another
        workspace's test produces no row, which the service turns into the same
        404 as a variant that does not exist.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            variant_id: Variant identifier.

        Returns:
            The variant, or ``None`` when it is not this workspace's.
        """
        stmt = (
            select(AbTestVariant)
            .join(AbTest, AbTest.id == AbTestVariant.test_id)
            .where(
                AbTestVariant.id == variant_id,
                AbTestVariant.test_id == test_id,
                AbTest.workspace_id == workspace_id,
            )
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

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
        """Return how many photos a test holds.

        The "Main photo" counts. It is an upload like the rest now — it used to be
        captured off WB's CDN, and excluding it from the cap was how the seller
        avoided paying a slot for a photo they never chose.

        Args:
            test_id: Owning test.

        Returns:
            The number of variants.
        """
        stmt = (
            select(func.count()).select_from(AbTestVariant).where(AbTestVariant.test_id == test_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def set_excluded(
        self, *, variant: AbTestVariant, excluded_at: datetime | None
    ) -> AbTestVariant:
        """Take a photo out of the rotation, or put it back.

        Nothing is deleted — not the row, not the image, not a single window
        already credited to it. The result table goes on showing what it earned;
        it just stops being dealt.

        Args:
            variant: The photo to change.
            excluded_at: When it left the rotation, or ``None`` to return it.

        Returns:
            The updated variant.
        """
        variant.excluded_at = excluded_at
        await self._session.flush()
        return variant

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
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        activated_at: datetime,
        round_number: int = 1,
        published_at: datetime | None = None,
    ) -> VariantExposure:
        """Record that a photo has just gone up.

        Called only after WB accepted the upload, so the table describes what
        happened rather than what was intended.

        Args:
            test_id: Owning test.
            variant_id: The photo now on the card.
            activated_at: When WB accepted it.
            round_number: Which lap of the rotation this turn belongs to.
            published_at: The CDN's ``Last-Modified`` once this install had
                landed — the witness later passes check the card against.
                ``None`` when it could not be read, which disables the check
                for this turn rather than arming it with a stale value.

        Returns:
            The new exposure row.
        """
        exposure = VariantExposure(
            test_id=test_id,
            variant_id=variant_id,
            activated_at=activated_at,
            round_number=round_number,
            published_at=published_at,
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

    async def published_at_of_open(self, *, test_id: uuid.UUID) -> datetime | None:
        """The witnessed publication time of the photo currently on the card.

        Args:
            test_id: Owning test.

        Returns:
            The open exposure's ``published_at``, or ``None`` when nothing is
            installed, when the row predates the witness, or when the install
            could not be vouched for. All three mean the same thing to the
            caller: there is nothing to compare the card against.
        """
        stmt = (
            select(VariantExposure.published_at)
            .where(
                VariantExposure.test_id == test_id,
                VariantExposure.deactivated_at.is_(None),
            )
            .order_by(VariantExposure.activated_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def current_round(self, *, test_id: uuid.UUID) -> int:
        """The highest lap number a test has reached, or 0 before it starts.

        Args:
            test_id: Owning test.

        Returns:
            The current round, counting from 1 once the first photo is up.
        """
        stmt = select(func.coalesce(func.max(VariantExposure.round_number), 0)).where(
            VariantExposure.test_id == test_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def history(self, *, test_id: uuid.UUID) -> list[VariantExposure]:
        """Every turn a test has served, newest first.

        Args:
            test_id: Owning test.

        Returns:
            Exposure rows, most recent installation first — the order the
            "Rotation history" table reads in.
        """
        stmt = (
            select(VariantExposure)
            .where(VariantExposure.test_id == test_id)
            .order_by(VariantExposure.activated_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

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
