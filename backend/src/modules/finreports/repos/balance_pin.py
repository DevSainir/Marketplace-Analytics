"""Data access for the balance grid's "Don't count" rows and columns."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.modules.finreports.models import BalancePin, BalancePinKind
from src.modules.finreports.repos.base import BaseRepository


class BalancePinRepository(BaseRepository):
    """The "Don't count" marks of the balance grid, keyed ``(workspace, kind, value)``."""

    model = BalancePin

    async def list_values(self, *, workspace_id: uuid.UUID, kind: BalancePinKind) -> set[str]:
        """Return the pinned values of one kind for a workspace.

        Args:
            workspace_id: Owning workspace.
            kind: Row marks (``SKU_UNCOUNTED``) or column marks
                (``WAREHOUSE_UNCOUNTED``).

        Returns:
            The marked values as text — ``nm_id``s for SKU marks, WB warehouse
            names for warehouse ones (empty when nothing is marked).
        """
        stmt = select(BalancePin.value).where(
            BalancePin.workspace_id == workspace_id, BalancePin.kind == kind.value
        )
        return {str(value) for value in (await self._session.execute(stmt)).scalars().all()}

    async def set_pinned(
        self, *, workspace_id: uuid.UUID, kind: BalancePinKind, value: str, pinned: bool
    ) -> None:
        """Set or clear one row's or column's mark.

        Idempotent both ways: marking an already-marked value is a no-op insert
        (``ON CONFLICT DO NOTHING``), and clearing an absent one deletes
        nothing — so a double click from two browser tabs cannot fail.

        Args:
            workspace_id: Owning workspace.
            kind: Row marks (``SKU_UNCOUNTED``) or column marks
                (``WAREHOUSE_UNCOUNTED``).
            value: ``nm_id`` as text, or the WB warehouse name.
            pinned: ``True`` to set the mark, ``False`` to clear it.
        """
        if pinned:
            stmt = (
                pg_insert(BalancePin)
                .values(workspace_id=workspace_id, kind=kind.value, value=value)
                .on_conflict_do_nothing(index_elements=["workspace_id", "kind", "value"])
            )
            await self._session.execute(stmt)
            return
        await self._session.execute(
            delete(BalancePin).where(
                BalancePin.workspace_id == workspace_id,
                BalancePin.kind == kind.value,
                BalancePin.value == value,
            )
        )
