"""Data access for A/B tests themselves.

Sole owner of SQL for ``ab_tests.ab_test``. Every read is scoped by
``workspace_id``: a test rewrites the seller's live card, so a leak across
tenants is not a privacy bug but a "someone else changed my storefront" bug.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import String, delete, func, or_, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.ab_tests.models import AbTest, AbTestStatus


class AbTestRepository:
    """Reads and writes A/B tests."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def create(
        self,
        *,
        workspace_id: uuid.UUID,
        nm_id: int,
        vendor_code: str,
        name: str,
        trigger_mode: str,
        impression_budget: int,
        slot_minutes: int,
    ) -> AbTest:
        """Insert a draft test.

        Args:
            workspace_id: Owning workspace.
            nm_id: The card whose main photo will rotate.
            vendor_code: Артикул продавца, denormalised for search.
            name: Human title.
            trigger_mode: Which trigger advances the rotation.
            impression_budget: Impressions one variant must gather, in
                ``impressions`` mode.
            slot_minutes: Minutes one variant stays up, in ``time`` mode.

        Returns:
            The persisted test, flushed so its id is available.
        """
        test = AbTest(
            workspace_id=workspace_id,
            nm_id=nm_id,
            vendor_code=vendor_code,
            name=name,
            status=AbTestStatus.DRAFT.value,
            trigger_mode=trigger_mode,
            impression_budget=impression_budget,
            slot_minutes=slot_minutes,
            # Marks the collection LOADED and empty, which it is. Without it the
            # first read of `test.variants` on the flushed instance emits a lazy
            # SELECT, and a lazy SELECT on an async session raises
            # MissingGreenlet — so building the response row for a test we had
            # just created answered 500.
            variants=[],
        )
        self._session.add(test)
        await self._session.flush()
        return test

    async def count_for_workspace(self, workspace_id: uuid.UUID) -> int:
        """Return how many tests this workspace holds, in any status.

        Draft, running and finished all count: a finished test keeps its rows,
        its variants and its images, so it is exactly as much stored data as a
        running one (register P1.13).

        Args:
            workspace_id: Owning workspace.

        Returns:
            The test count.
        """
        stmt = select(func.count()).select_from(AbTest).where(AbTest.workspace_id == workspace_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def pause_for_ads(self, *, test: AbTest, at: datetime) -> None:
        """Pause a test because its advertising stopped, flagging why.

        The flag is the whole point. A test paused by hand and one paused by the
        rotation are the same ``status``, and only one of them may start itself
        again — resuming the other would override the seller's own decision on
        the next polling pass.

        Args:
            test: The running test to pause.
            at: The polling pass's own clock, stamped as the moment it stopped —
                the same instant the window that ended here was closed at, so
                the page cannot show a pause that began after the last figure it
                is displaying.
        """
        test.status = AbTestStatus.PAUSED.value
        test.paused_by_ads = True
        test.stopped_at = at
        await self._session.flush()

    async def resume_after_ads(self, *, test: AbTest) -> None:
        """Put an ads-paused test back to running.

        Args:
            test: The test whose campaign is serving again.
        """
        test.status = AbTestStatus.RUNNING.value
        test.paused_by_ads = False
        test.stopped_at = None
        await self._session.flush()

    async def list_ads_paused(self) -> list[AbTest]:
        """Tests the rotation paused, across every workspace.

        The polling sweep walks these alongside the running ones so a campaign
        coming back on brings its test with it, with no one having to notice.
        A test the SELLER paused is deliberately absent.

        Returns:
            Paused tests carrying the flag, with their variants loaded.
        """
        stmt = (
            select(AbTest)
            .where(
                AbTest.status == AbTestStatus.PAUSED.value,
                AbTest.paused_by_ads.is_(True),
            )
            .options(selectinload(AbTest.variants))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest | None:
        """Return one test with its variants loaded, or ``None``.

        Args:
            workspace_id: Tenancy guard — a foreign test reads as absent.
            test_id: Test identifier.

        Returns:
            The test, or ``None`` when it does not exist in this workspace.
        """
        stmt = (
            select(AbTest)
            .where(AbTest.id == test_id, AbTest.workspace_id == workspace_id)
            .options(selectinload(AbTest.variants))
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

    async def search(
        self,
        *,
        workspace_id: uuid.UUID,
        query: str | None = None,
        statuses: Sequence[str] | None = None,
    ) -> list[AbTest]:
        """List the workspace's tests, newest first, optionally filtered.

        ``query`` matches any of the fields the list shows — the test's name,
        the WB article and the seller's article — so the one search box in the
        header behaves the way the cabinet's does. The nm is matched as text
        because users paste partial articles.

        Args:
            workspace_id: Owning workspace.
            query: Free-text needle; ``None`` or blank returns everything.
            statuses: Restrict to these statuses when given.

        Returns:
            Matching tests with their variants loaded, newest first.
        """
        stmt = (
            select(AbTest)
            .where(AbTest.workspace_id == workspace_id)
            .options(selectinload(AbTest.variants))
            .order_by(AbTest.created_at.desc())
        )

        needle = (query or "").strip()
        if needle:
            pattern = f"%{needle.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(AbTest.name).like(pattern),
                    func.lower(AbTest.vendor_code).like(pattern),
                    sa_cast(AbTest.nm_id, String).like(f"%{needle}%"),
                    func.lower(AbTest.status).like(pattern),
                )
            )

        if statuses:
            stmt = stmt.where(AbTest.status.in_(list(statuses)))

        return list((await self._session.execute(stmt)).scalars().all())

    async def list_advanceable(self) -> list[AbTest]:
        """Return every running test, across all workspaces.

        Used by the nightly rotation pass, which is not request-scoped and so
        has no workspace of its own.

        Returns:
            Running tests with their variants loaded.
        """
        stmt = (
            select(AbTest)
            .where(AbTest.status == AbTestStatus.RUNNING.value)
            .options(selectinload(AbTest.variants))
            .order_by(AbTest.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def update_settings(
        self,
        *,
        test: AbTest,
        name: str | None,
        trigger_mode: str,
        impression_budget: int,
        slot_minutes: int,
    ) -> None:
        """Write a test's name and resolved trigger settings.

        Both numbers are written even though only one is in force, so switching
        modes back and forth does not lose what the other was set to.

        Args:
            test: The test to update (already loaded and tenancy-checked).
            name: New title, or ``None`` to leave it.
            trigger_mode: The resolved mode.
            impression_budget: The resolved budget.
            slot_minutes: The resolved slot length.
        """
        if name is not None:
            test.name = name
        test.trigger_mode = trigger_mode
        test.impression_budget = impression_budget
        test.slot_minutes = slot_minutes
        await self._session.flush()

    async def set_status(
        self,
        *,
        test: AbTest,
        status: AbTestStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None:
        """Move a test to a new status, stamping the lifecycle timestamps.

        ``stopped_at`` is cleared by any transition into ``RUNNING`` rather than
        left for the caller to remember: it is the answer to «сколько тест уже
        стоит», and a value surviving a resume would keep answering it for a
        test that is moving again.

        Args:
            test: The test to update (already loaded).
            status: New status.
            started_at: Set on the first transition into ``RUNNING``.
            finished_at: Set when the test stops for good.
            stopped_at: When the rotation stopped advancing — a pause as much as
                a finish. Ignored for ``RUNNING``, which clears it.
        """
        test.status = status.value
        if started_at is not None:
            test.started_at = started_at
        if finished_at is not None:
            test.finished_at = finished_at
        if status is AbTestStatus.RUNNING:
            test.stopped_at = None
        elif stopped_at is not None:
            test.stopped_at = stopped_at
        await self._session.flush()

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID | None) -> None:
        """Record which variant is currently on the card.

        Args:
            test: The test to update.
            variant_id: The live variant, or ``None`` when none is.
        """
        test.active_variant_id = variant_id
        await self._session.flush()

    async def delete(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> bool:
        """Delete a test and everything hanging off it.

        Args:
            workspace_id: Tenancy guard.
            test_id: Test identifier.

        Returns:
            ``True`` when a row was removed.
        """
        stmt = delete(AbTest).where(AbTest.id == test_id, AbTest.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return bool(cast("CursorResult[Any]", result).rowcount)
