"""SQL for the heatmap's groups — the module's only tables.

Every statement carries the tenant in its ``WHERE`` (or in the row it writes),
so a group id from another кабинет matches nothing rather than being fetched
and discarded. Row-level security enforces the same thing a second time in
production; this is the layer that makes it true everywhere else.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.heatmap.models import SkuGroup, SkuGroupItem


class SkuGroupRepository:
    """Reads and writes one кабинет's groups."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def list_groups(self, workspace_id: uuid.UUID) -> list[tuple[uuid.UUID, str, list[int]]]:
        """Return ``(id, name, nm_ids)`` for every group of the кабинет, by name."""
        groups = (
            await self._session.execute(
                select(SkuGroup.id, SkuGroup.name)
                .where(SkuGroup.workspace_id == workspace_id)
                .order_by(func.lower(SkuGroup.name), SkuGroup.id)
            )
        ).all()
        members: dict[uuid.UUID, list[int]] = {group_id: [] for group_id, _ in groups}
        rows = await self._session.execute(
            select(SkuGroupItem.group_id, SkuGroupItem.nm_id)
            .where(SkuGroupItem.workspace_id == workspace_id)
            .order_by(SkuGroupItem.nm_id)
        )
        for group_id, nm_id in rows.all():
            members.setdefault(group_id, []).append(int(nm_id))
        return [(group_id, name, members[group_id]) for group_id, name in groups]

    async def count(self, workspace_id: uuid.UUID) -> int:
        """How many groups the кабинет holds."""
        stmt = (
            select(func.count()).select_from(SkuGroup).where(SkuGroup.workspace_id == workspace_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def exists(self, workspace_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        """Whether ``group_id`` is one of THIS кабинет's groups."""
        stmt = select(SkuGroup.id).where(
            SkuGroup.id == group_id, SkuGroup.workspace_id == workspace_id
        )
        return (await self._session.execute(stmt)).first() is not None

    async def name_taken(
        self, workspace_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None
    ) -> bool:
        """Whether another group of the кабинет already has this name, ignoring case."""
        stmt = select(SkuGroup.id).where(
            SkuGroup.workspace_id == workspace_id, func.lower(SkuGroup.name) == name.lower()
        )
        if except_id is not None:
            stmt = stmt.where(SkuGroup.id != except_id)
        return (await self._session.execute(stmt)).first() is not None

    async def create(self, workspace_id: uuid.UUID, name: str) -> uuid.UUID:
        """Insert a group and return its id."""
        group = SkuGroup(workspace_id=workspace_id, name=name)
        self._session.add(group)
        await self._session.flush()
        return group.id

    async def rename(self, workspace_id: uuid.UUID, group_id: uuid.UUID, name: str) -> None:
        """Rename one of the кабинет's groups."""
        group = (
            await self._session.execute(
                select(SkuGroup).where(
                    SkuGroup.id == group_id, SkuGroup.workspace_id == workspace_id
                )
            )
        ).scalar_one()
        group.name = name
        await self._session.flush()

    async def replace_members(
        self, workspace_id: uuid.UUID, group_id: uuid.UUID, nm_ids: Collection[int]
    ) -> None:
        """Make ``nm_ids`` exactly the group's members."""
        await self._session.execute(
            delete(SkuGroupItem).where(
                SkuGroupItem.group_id == group_id, SkuGroupItem.workspace_id == workspace_id
            )
        )
        self._session.add_all(
            SkuGroupItem(group_id=group_id, nm_id=nm_id, workspace_id=workspace_id)
            for nm_id in sorted(set(nm_ids))
        )
        await self._session.flush()

    async def delete(self, workspace_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        """Delete one of the кабинет's groups; ``False`` when it is not one."""
        result = await self._session.execute(
            delete(SkuGroup).where(SkuGroup.id == group_id, SkuGroup.workspace_id == workspace_id)
        )
        return bool(getattr(result, "rowcount", 0))
