"""The heatmap's «Группы»: named sets of articles a seller assembles and reuses.

A group is replaced whole on every edit — name and members together — because
that is how the dialog works (one form, one «Сохранить») and because it leaves
no half-edited group behind a failed request.

Every article is proved to be the workspace's own before it is written. WB article
numbers are global, so «this article exists» and «this article is yours» are
different questions, and a group holding a stranger's card would paint that
card's name into this workspace's filter the next time the catalogue changed
hands. The error says how many were refused, never which: the rule is not to
echo rejected input back.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.modules.heatmap.repos import SkuGroupRepository
from src.modules.heatmap.schemas import SkuGroupList, SkuGroupRead, SkuGroupWrite
from src.modules.monitoring.contract import load_workspace_catalog


class SkuGroupService:
    """Lists, creates, edits and deletes one workspace's groups."""

    def __init__(self, repo: SkuGroupRepository) -> None:
        """Wire the service from its repository."""
        self._repo = repo

    async def list_groups(self, *, workspace_id: uuid.UUID) -> SkuGroupList:
        """Every group of the workspace, alphabetically."""
        return SkuGroupList(
            items=[
                SkuGroupRead(id=group_id, name=name, nm_ids=nm_ids)
                for group_id, name, nm_ids in await self._repo.list_groups(workspace_id)
            ]
        )

    async def create(
        self, session: AsyncSession, *, workspace_id: uuid.UUID, payload: SkuGroupWrite
    ) -> SkuGroupRead:
        """Create a group from a name and a set of the workspace's articles.

        Raises:
            ValidationError: An article is not in the workspace's catalogue, or the
                workspace is at its group bound.
            ConflictError: Another group already has this name.
        """
        await self._check_members(session, workspace_id, payload.nm_ids)
        cap = settings.max_sku_groups_per_workspace
        if await self._repo.count(workspace_id) >= cap:
            raise ValidationError(f"Достигнут лимит групп ({cap} на кабинет).")
        if await self._repo.name_taken(workspace_id, payload.name):
            raise ConflictError("Группа с таким названием уже есть.")
        group_id = await self._repo.create(workspace_id, payload.name)
        await self._repo.replace_members(workspace_id, group_id, payload.nm_ids)
        return SkuGroupRead(id=group_id, name=payload.name, nm_ids=sorted(set(payload.nm_ids)))

    async def update(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        group_id: uuid.UUID,
        payload: SkuGroupWrite,
    ) -> SkuGroupRead:
        """Replace a group's name and members.

        Raises:
            NotFoundError: The group is not one of this workspace's — reported as
                missing rather than forbidden, so a guessed id confirms nothing.
            ValidationError: An article is not in the workspace's catalogue.
            ConflictError: Another group already has this name.
        """
        if not await self._repo.exists(workspace_id, group_id):
            raise NotFoundError("Группа не найдена.")
        await self._check_members(session, workspace_id, payload.nm_ids)
        if await self._repo.name_taken(workspace_id, payload.name, except_id=group_id):
            raise ConflictError("Группа с таким названием уже есть.")
        await self._repo.rename(workspace_id, group_id, payload.name)
        await self._repo.replace_members(workspace_id, group_id, payload.nm_ids)
        return SkuGroupRead(id=group_id, name=payload.name, nm_ids=sorted(set(payload.nm_ids)))

    async def delete(self, *, workspace_id: uuid.UUID, group_id: uuid.UUID) -> None:
        """Delete a group; its articles are untouched.

        Raises:
            NotFoundError: The group is not one of this workspace's.
        """
        if not await self._repo.delete(workspace_id, group_id):
            raise NotFoundError("Группа не найдена.")

    async def _check_members(
        self, session: AsyncSession, workspace_id: uuid.UUID, nm_ids: list[int]
    ) -> None:
        """Refuse any article the workspace does not own."""
        cards = await load_workspace_catalog(session, workspace_id=workspace_id)
        owned = {card.nm_id for card in cards}
        unknown = len(set(nm_ids) - owned)
        if unknown:
            raise ValidationError(f"Артикулов нет в каталоге кабинета: {unknown}.")
