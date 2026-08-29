"""Data-access layer for the Workspaces module.

Repositories are the *only* code permitted to build and execute SQLAlchemy
statements for this module. Services depend on these classes and never touch
the :class:`AsyncSession` query API directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.workspaces.models import Workspace, WorkspaceToken


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
        for every customer on one schedule. No request-scoped caller may use
        this — :meth:`list_for_organization` is the one for those.
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

    async def delete(self, workspace: Workspace) -> None:
        """Delete a workspace (its tokens cascade via the FK)."""
        await self._session.delete(workspace)
        await self._session.flush()


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
