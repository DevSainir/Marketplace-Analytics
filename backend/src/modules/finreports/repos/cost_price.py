"""Data access for the seller's own per-SKU cost prices."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.modules.finreports.models import ProductCostPrice
from src.modules.finreports.repos.base import BaseRepository

#: Columns overwritten when a cost is re-entered for a SKU already on file.
#: ``updated_at`` is set separately — see :meth:`CostPriceRepository.upsert_many`.
_COST_UPDATE = ["cost", "currency", "vendor_code", "source", "note"]


class CostPriceRepository(BaseRepository):
    """The seller-entered cost of goods, one current figure per SKU."""

    model = ProductCostPrice

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[ProductCostPrice]:
        """Return every cost price on file for a workspace, by SKU.

        Args:
            workspace_id: Owning workspace.

        Returns:
            The workspace's cost rows ordered by ``nm_id`` (stable for the UI).
        """
        stmt = (
            select(ProductCostPrice)
            .where(ProductCostPrice.workspace_id == workspace_id)
            .order_by(ProductCostPrice.nm_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_for_workspace(self, workspace_id: uuid.UUID) -> int:
        """Return how many SKUs this workspace has a cost on file for.

        Args:
            workspace_id: Owning workspace.

        Returns:
            The row count. Indexed by the primary key's leading column, so this
            is cheap enough to run on the write path.
        """
        stmt = (
            select(func.count())
            .select_from(ProductCostPrice)
            .where(ProductCostPrice.workspace_id == workspace_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_existing(self, *, workspace_id: uuid.UUID, nm_ids: Sequence[int]) -> int:
        """Return how many of these SKUs already have a cost on file.

        The quota check needs to know how many rows a batch would *add*, not
        how many it touches: overwriting a cost the workspace already stores
        consumes no new storage, and counting it would refuse a customer
        re-uploading their own catalogue.

        Args:
            workspace_id: Owning workspace.
            nm_ids: The SKUs in the incoming batch.

        Returns:
            How many of them are already stored.
        """
        if not nm_ids:
            return 0
        stmt = (
            select(func.count())
            .select_from(ProductCostPrice)
            .where(
                ProductCostPrice.workspace_id == workspace_id,
                ProductCostPrice.nm_id.in_(set(nm_ids)),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def costs_by_nm_id(self, *, workspace_id: uuid.UUID, currency: str) -> dict[int, Decimal]:
        """Return ``{nm_id: cost}`` for the SKUs costed in a given currency.

        Filtering on the currency here rather than in the service is deliberate:
        the P&L must never apply a cost stated in one currency to a settlement
        made in another. A row in the wrong currency is simply absent from the
        mapping, and the caller reports the SKU as uncosted instead of silently
        converting at an invented rate.

        Args:
            workspace_id: Owning workspace.
            currency: Settlement currency the costs must match (e.g. ``KGS``).

        Returns:
            ``{nm_id: cost per unit}``; SKUs with no matching row are absent.
        """
        stmt = select(ProductCostPrice.nm_id, ProductCostPrice.cost).where(
            ProductCostPrice.workspace_id == workspace_id,
            ProductCostPrice.currency == currency,
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.nm_id: row.cost for row in rows}

    async def upsert_many(self, rows: Sequence[dict[str, object]]) -> int:
        """Insert or overwrite cost prices, keyed ``(workspace_id, nm_id)``.

        Not :meth:`BaseRepository.bulk_upsert`, because this table needs
        ``updated_at`` to move. The model's ``onupdate=func.now()`` is a Core hook
        that only fires on ORM-issued UPDATEs; ``ON CONFLICT DO UPDATE SET`` never
        triggers it, so a re-entered cost would keep the timestamp of the original
        seed. That timestamp is the only trail an unverifiable, hand-entered
        figure has — a restatement that leaves no mark is exactly what it must not
        be able to do.

        Args:
            rows: Mappings carrying at least ``workspace_id``, ``nm_id``, ``cost``.

        Returns:
            The number of rows submitted.
        """
        if not rows:
            return 0
        stmt = pg_insert(ProductCostPrice).values(list(rows))
        excluded = stmt.excluded
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["workspace_id", "nm_id"],
                set_={
                    **{column: excluded[column] for column in _COST_UPDATE},
                    "updated_at": func.now(),
                },
            )
        )
        return len(rows)

    async def delete_one(self, *, workspace_id: uuid.UUID, nm_id: int) -> int:
        """Remove one SKU's cost price.

        Args:
            workspace_id: Owning workspace.
            nm_id: SKU whose cost is dropped.

        Returns:
            ``1`` if a row was removed, ``0`` if there was nothing on file.
        """
        stmt = delete(ProductCostPrice).where(
            ProductCostPrice.workspace_id == workspace_id,
            ProductCostPrice.nm_id == nm_id,
        )
        # A DML statement always yields a CursorResult; the base Result type does
        # not declare rowcount, so the narrowing is stated rather than ignored.
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return int(result.rowcount or 0)
