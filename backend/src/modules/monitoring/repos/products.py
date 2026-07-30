"""Repositories for the product catalogue dimensions.

Own all SQL for :class:`ProductCard` (nm_id -> vendor_code/title) and
:class:`ProductSize` (chrt_id -> tech_size/wb_size). The ingestion service upserts
into them from the Content API; the analytics service reads them to decorate the
summary/detail/stock DTOs with human vendor codes and size labels.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import ProductCard, ProductSize
from src.modules.monitoring.repos.base import BaseRepository

_CARD_CONFLICT = ("nm_id",)
_CARD_UPDATE = ("workspace_id", "vendor_code", "title", "synced_at")

_SIZE_CONFLICT = ("chrt_id",)
_SIZE_UPDATE = ("nm_id", "tech_size", "wb_size", "synced_at")


class ProductCardRepository(BaseRepository):
    """CRUD/read operations for the ``product_card`` dimension."""

    model = ProductCard

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert product cards keyed by ``nm_id``.

        Args:
            rows: Column->value mappings for each card.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(
            rows, conflict_columns=_CARD_CONFLICT, update_columns=_CARD_UPDATE
        )

    async def get_by_ids(self, nm_ids: Iterable[int]) -> dict[int, ProductCard]:
        """Return cards for the given SKUs, keyed by ``nm_id``.

        Args:
            nm_ids: SKU ids to look up.

        Returns:
            A mapping of ``nm_id -> ProductCard`` (missing ids are omitted).
        """
        ids = list(nm_ids)
        if not ids:
            return {}
        stmt = select(ProductCard).where(ProductCard.nm_id.in_(ids))
        result = await self._session.execute(stmt)
        return {c.nm_id: c for c in result.scalars().all()}

    async def search_by_vendor_code(
        self, fragment: str, *, workspace_id: uuid.UUID, limit: int
    ) -> list[ProductCard]:
        """Return cards whose vendor code contains ``fragment`` (case-insensitive).

        Resolves the seller-facing "Артикул продавца" search: a partial code like
        ``"M-TRX01"`` returns every colourway card (``M-TRX01-BLK``,
        ``M-TRX01-BEJ``, ...), so the caller can pick a concrete ``nm_id``.

        Args:
            fragment: Vendor-code substring to match (already stripped/non-empty).
            workspace_id: Restrict to SKUs owned by this workspace.
            limit: Maximum number of cards to return.

        Returns:
            Matching cards ordered by vendor code, capped at ``limit``.
        """
        pattern = f"%{fragment}%"
        stmt = (
            select(ProductCard)
            .where(
                ProductCard.vendor_code.ilike(pattern),
                ProductCard.workspace_id == workspace_id,
            )
            .order_by(ProductCard.vendor_code)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def is_in_workspace(self, *, nm_id: int, workspace_id: uuid.UUID) -> bool:
        """Report whether a SKU is registered to the given workspace.

        The single ownership check backing the per-SKU route guard: a SKU that
        belongs to another workspace (or is unregistered) must behave exactly
        like a SKU that does not exist.

        Args:
            nm_id: WB SKU identifier from the request path.
            workspace_id: The caller's active workspace.

        Returns:
            ``True`` when ``product_card`` records this SKU under the workspace.
        """
        stmt = select(ProductCard.nm_id).where(
            ProductCard.nm_id == nm_id,
            ProductCard.workspace_id == workspace_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_workspace_nm_ids(self, workspace_id: uuid.UUID) -> list[int]:
        """Return every SKU registered to a workspace, ascending by ``nm_id``.

        Backs the bulk «Обновить все SKU» refresh (enqueue a harvest over the
        whole catalogue) and the fake-harvest discovery path (which re-harvests
        the SKUs already on file instead of calling the Content API).

        Args:
            workspace_id: The workspace whose catalogue to enumerate.

        Returns:
            The workspace's ``nm_id`` list (empty when it owns no SKUs yet).
        """
        stmt = (
            select(ProductCard.nm_id)
            .where(ProductCard.workspace_id == workspace_id)
            .order_by(ProductCard.nm_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_workspace_of_sku(self, nm_id: int) -> uuid.UUID | None:
        """Return the owning workspace of a SKU, or ``None`` if unregistered.

        Used by the single-SKU refresh task to pick the WB credentials the
        harvest must run with.

        Args:
            nm_id: WB SKU identifier.

        Returns:
            The workspace id recorded in ``product_card``, if any.
        """
        stmt = select(ProductCard.workspace_id).where(ProductCard.nm_id == nm_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class ProductSizeRepository(BaseRepository):
    """CRUD/read operations for the ``product_size`` dimension."""

    model = ProductSize

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert size labels keyed by ``chrt_id``.

        Args:
            rows: Column->value mappings for each size characteristic.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(
            rows, conflict_columns=_SIZE_CONFLICT, update_columns=_SIZE_UPDATE
        )

    async def get_labels_by_chrt_ids(self, chrt_ids: Iterable[int]) -> dict[int, str]:
        """Return a ``chrt_id -> tech_size`` label map for the given ids.

        The label-less stock rows carry only ``chrt_id``; this resolves each to
        its human "Размер вещи" so the detail view can show a size instead of a
        bare characteristic id. Missing ids are simply omitted (callers treat an
        absent label as ``None``, so old/unsynced rows keep working).

        Args:
            chrt_ids: Size characteristic ids to resolve.

        Returns:
            A mapping of ``chrt_id -> tech_size`` (blank labels omitted).
        """
        ids = list(chrt_ids)
        if not ids:
            return {}
        stmt = select(ProductSize.chrt_id, ProductSize.tech_size).where(
            ProductSize.chrt_id.in_(ids)
        )
        result = await self._session.execute(stmt)
        return {chrt_id: label for chrt_id, label in result.all() if label}
