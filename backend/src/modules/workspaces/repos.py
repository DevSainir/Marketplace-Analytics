"""Data-access layer for the Workspaces module.

Repositories are the *only* code permitted to build and execute SQLAlchemy
statements for this module. Services depend on these classes and never touch
the :class:`AsyncSession` query API directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.modules.workspaces.models import (
    BackfillLane,
    BackfillState,
    Workspace,
    WorkspaceBackfill,
    WorkspaceGuest,
    WorkspaceToken,
)


class WorkspaceRepository:
    """CRUD operations for :class:`Workspace` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        """Return a workspace by primary key, or ``None`` if absent."""
        return await self._session.get(Workspace, workspace_id)

    async def get_by_name(self, name: str) -> Workspace | None:
        """Return a workspace by unique name, or ``None`` if absent."""
        stmt = select(Workspace).where(Workspace.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Workspace]:
        """Return one organisation's workspaces, oldest first.

        The tenant-facing listing. Every caller that is not the harvest uses
        this one — :meth:`list_all` exists only for the fan-out, which
        deliberately crosses tenants.
        """
        stmt = (
            select(Workspace)
            .where(Workspace.organization_id == organization_id)
            .order_by(Workspace.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_organization(self, organization_id: uuid.UUID) -> int:
        """Count an organisation's workspaces (for the subscription quota)."""
        stmt = (
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.organization_id == organization_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_all(self) -> list[Workspace]:
        """Return EVERY workspace across every tenant, oldest first.

        Cross-tenant on purpose, and the only method here that is: the Celery
        harvest fans out over all workspaces because WB data has to be fetched
        for every customer on one schedule. The one request-scoped caller is
        the dev's guest-grant form (``DevAccess``, names only); no tenant route
        may use this — :meth:`list_for_organization` is the one for those.
        """
        stmt = select(Workspace).order_by(Workspace.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, *, organization_id: uuid.UUID, name: str) -> Workspace:
        """Insert and flush a new workspace, returning the populated instance.

        Args:
            organization_id: The owning tenant.
            name: Unique workspace name.

        Returns:
            The persisted :class:`Workspace` with its generated id populated.
        """
        workspace = Workspace(organization_id=organization_id, name=name)
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def set_ads_show_bonus(self, workspace: Workspace, value: bool) -> None:
        """Store the "Promo bonuses" switch of one workspace."""
        workspace.ads_show_bonus = value
        await self._session.flush()

    async def delete(self, workspace: Workspace) -> None:
        """Delete a workspace (its tokens cascade via the FK)."""
        await self._session.delete(workspace)
        await self._session.flush()


class WorkspaceGuestRepository:
    """Grants that open one workspace, read-only, to a head of another company."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def exists(self, *, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether this person holds a grant on this workspace."""
        stmt = select(WorkspaceGuest.id).where(
            WorkspaceGuest.workspace_id == workspace_id, WorkspaceGuest.user_id == user_id
        )
        return (await self._session.execute(stmt)).first() is not None

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        """The workspaces granted to one person, oldest first."""
        stmt = (
            select(Workspace)
            .join(WorkspaceGuest, WorkspaceGuest.workspace_id == Workspace.id)
            .where(WorkspaceGuest.user_id == user_id)
            .order_by(Workspace.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all(self) -> list[tuple[WorkspaceGuest, str]]:
        """Every grant on the platform with its workspace name — the dev listing."""
        stmt = (
            select(WorkspaceGuest, Workspace.name)
            .join(Workspace, Workspace.id == WorkspaceGuest.workspace_id)
            .order_by(WorkspaceGuest.id)
        )
        return [(guest, name) for guest, name in (await self._session.execute(stmt)).all()]

    async def add(
        self, *, workspace_id: uuid.UUID, user_id: uuid.UUID, granted_by: uuid.UUID
    ) -> WorkspaceGuest:
        """Grant, or return the grant that already exists (idempotent).

        ``ON CONFLICT DO NOTHING`` rather than check-then-insert, so two
        simultaneous grants of the same pair end in one row, not an error.
        """
        await self._session.execute(
            pg_insert(WorkspaceGuest)
            .values(
                id=uuid7(),
                workspace_id=workspace_id,
                user_id=user_id,
                granted_by_user_id=granted_by,
            )
            .on_conflict_do_nothing(constraint="uq_workspace_guests_workspace_user")
        )
        stmt = select(WorkspaceGuest).where(
            WorkspaceGuest.workspace_id == workspace_id, WorkspaceGuest.user_id == user_id
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def remove(self, grant_id: uuid.UUID) -> WorkspaceGuest | None:
        """Delete one grant by id, returning it, or ``None`` if there was none."""
        stmt = delete(WorkspaceGuest).where(WorkspaceGuest.id == grant_id).returning(WorkspaceGuest)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class WorkspaceTokenRepository:
    """CRUD operations for encrypted :class:`WorkspaceToken` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[WorkspaceToken]:
        """Return every token row of one workspace."""
        stmt = select(WorkspaceToken).where(WorkspaceToken.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[WorkspaceToken]:
        """Return every token row across all workspaces (harvest fan-out)."""
        stmt = select(WorkspaceToken)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: str,
        token_encrypted: str,
    ) -> WorkspaceToken:
        """Insert or replace the token of one (workspace, surface) pair.

        Args:
            workspace_id: Owning workspace id.
            kind: WB API surface (:class:`~.models.TokenKind` value).
            token_encrypted: Fernet ciphertext of the bearer token.

        Returns:
            The persisted :class:`WorkspaceToken` row.
        """
        stmt = select(WorkspaceToken).where(
            WorkspaceToken.workspace_id == workspace_id,
            WorkspaceToken.kind == kind,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            row = WorkspaceToken(
                workspace_id=workspace_id, kind=kind, token_encrypted=token_encrypted
            )
            self._session.add(row)
        else:
            row.token_encrypted = token_encrypted
        await self._session.flush()
        return row

    async def delete_kind(self, *, workspace_id: uuid.UUID, kind: str) -> None:
        """Remove the stored token of one (workspace, surface) pair, if any."""
        stmt = delete(WorkspaceToken).where(
            WorkspaceToken.workspace_id == workspace_id,
            WorkspaceToken.kind == kind,
        )
        await self._session.execute(stmt)


class BackfillRepository:
    """Reads and writes one workspace's per-lane backfill progress.

    Every write is an UPSERT keyed by ``(workspace_id, lane)``: a lane's row is
    created by whichever tick reaches it first, and the tick that follows an
    hour later must update that row rather than discover it is missing. The
    tasks that call this are re-entrant by design — Celery may deliver a tick
    twice — so nothing here may depend on having seen the previous one.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected async session."""
        self._session = session

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[WorkspaceBackfill]:
        """Return every lane row of one workspace, in lane order."""
        stmt = (
            select(WorkspaceBackfill)
            .where(WorkspaceBackfill.workspace_id == workspace_id)
            .order_by(WorkspaceBackfill.lane)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, *, workspace_id: uuid.UUID, lane: str) -> WorkspaceBackfill | None:
        """Return one lane's row, or ``None`` before it has ever ticked."""
        return await self._session.get(WorkspaceBackfill, (workspace_id, lane))

    async def upsert(
        self,
        *,
        workspace_id: uuid.UUID,
        lane: str,
        state: str | None = None,
        done_units: int | None = None,
        total_units: int | None = None,
        cursor: str | None = None,
        message: str | None = None,
    ) -> WorkspaceBackfill:
        """Create or update one lane's row, touching only what is passed.

        Every field is optional so a tick can report what it knows without
        overwriting what it does not: the funnel walk advances ``done_units``
        and ``cursor`` on each tick while ``total_units`` was set once at the
        start, and a partial write must not reset the estimate to zero.

        ``started_at`` is stamped the first time the lane goes RUNNING and
        ``finished_at`` when it reaches a terminal state, so neither has to be
        passed by a caller that is only moving the counter.

        Args:
            workspace_id: Owning workspace.
            lane: :class:`~.models.BackfillLane` value.
            state: New :class:`~.models.BackfillState`, if it changed.
            done_units: Progress numerator, if it advanced.
            total_units: Progress denominator, if it was (re)estimated.
            cursor: The lane's private resume point, if it moved.
            message: User-facing status line, if it changed.

        Returns:
            The persisted row.
        """
        row = await self.get(workspace_id=workspace_id, lane=lane)
        if row is None:
            row = WorkspaceBackfill(workspace_id=workspace_id, lane=lane)
            self._session.add(row)
        if state is not None:
            if state == BackfillState.RUNNING and row.started_at is None:
                row.started_at = datetime.now(UTC)
            if state in (BackfillState.DONE, BackfillState.FAILED):
                row.finished_at = datetime.now(UTC)
            row.state = state
        if done_units is not None:
            row.done_units = done_units
        if total_units is not None:
            row.total_units = total_units
        if cursor is not None:
            row.cursor = cursor
        if message is not None:
            row.message = message
        # Stamped unconditionally, because this row records an ATTEMPT and not
        # just its content. Left to ``onupdate`` it fires only when some column
        # actually changes value — and the commonest healthy tick changes none
        # of them: a lane waiting out WB's window writes the same message every
        # time. Observed on one workspace 2026-09-15, a lane that had ticked twenty
        # seconds earlier reported ``updated_at`` 2h51m old.
        #
        # Everything that judges whether a lane is alive reads this column. The
        # watchdog restarts what has not moved, and that restart then waits a
        # further window before asking (`LANE_RESTART_DELAY`, a quarter of an
        # hour on the settlement endpoint, ninety seconds since), so a lane that
        # was working perfectly pays for being quiet.
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def reset(self, workspace_id: uuid.UUID, lanes: Collection[BackfillLane]) -> None:
        """Drop the named lane rows of one workspace, so those lanes start over.

        Named rather than "every row": a token that unlocks one lane must not
        wipe the progress of the others, nor the maintenance lanes the profile
        never renders.
        """
        stmt = delete(WorkspaceBackfill).where(
            WorkspaceBackfill.workspace_id == workspace_id,
            WorkspaceBackfill.lane.in_([str(lane) for lane in lanes]),
        )
        await self._session.execute(stmt)
