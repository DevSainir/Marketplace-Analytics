"""The global pinned-SKU chips («Закрепить»): list, pin, reorder, paint."""

from __future__ import annotations

import uuid

from src.core.exceptions import ValidationError
from src.modules.monitoring.repos import PinnedSkuRepository, ProductCardRepository
from src.modules.monitoring.schemas import PinnedSkuItem, PinnedSkusResponse


class PinnedSkuAnalytics:
    """Manages the workspace's pinned-SKU chip row."""

    def __init__(
        self,
        *,
        pinned_sku_repo: PinnedSkuRepository,
        product_card_repo: ProductCardRepository,
    ) -> None:
        """Inject the pin store and the catalogue used to decorate chips."""
        self._pinned_skus = pinned_sku_repo
        self._product_cards = product_card_repo

    async def list_pinned_skus(self, *, workspace_id: uuid.UUID) -> PinnedSkusResponse:
        """Return the workspace's pinned-SKU list, decorated with catalogue identity.

        Pins are shared by every account (a team watchlist, not a personal
        one) but scoped to the active workspace's SKUs; order is the manual
        drag-and-drop order, falling back to pin order (oldest first).

        Args:
            workspace_id: The caller's active workspace.

        Returns:
            The :class:`PinnedSkusResponse` chip-row payload.
        """
        rows = await self._pinned_skus.list_rows(workspace_id=workspace_id)
        cards = await self._product_cards.get_by_ids([row.nm_id for row in rows])
        return PinnedSkusResponse(
            items=[
                PinnedSkuItem(
                    nm_id=row.nm_id,
                    vendor_code=cards[row.nm_id].vendor_code if row.nm_id in cards else None,
                    title=cards[row.nm_id].title if row.nm_id in cards else None,
                    color=row.color,
                )
                for row in rows
            ]
        )

    async def set_sku_pin(
        self, *, workspace_id: uuid.UUID, nm_id: int, pinned: bool
    ) -> PinnedSkusResponse:
        """Pin or unpin one SKU (idempotent both ways).

        Args:
            workspace_id: The caller's active workspace (scopes the returned
                list; the ``nm_id`` itself is ownership-guarded by the router).
            nm_id: WB SKU identifier.
            pinned: ``True`` to pin, ``False`` to unpin.

        Returns:
            The full pinned list after the update (the chip row re-renders
            from it, so concurrent pins by teammates surface immediately).
        """
        if pinned:
            await self._pinned_skus.add(nm_id=nm_id)
        else:
            await self._pinned_skus.remove(nm_id=nm_id)
        return await self.list_pinned_skus(workspace_id=workspace_id)

    async def reorder_pins(
        self, *, workspace_id: uuid.UUID, nm_ids: list[int]
    ) -> PinnedSkusResponse:
        """Rewrite the chip row's order after a drag-and-drop.

        The submitted list must be exactly the workspace's current pins. That
        is both the tenancy guard (a foreign or unpinned ``nm_id`` cannot be
        positioned) and a staleness guard: if a teammate pinned or unpinned
        while this row was being dragged, the reorder is rejected rather than
        silently applied to an order that no longer describes the row.

        Args:
            workspace_id: The caller's active workspace.
            nm_ids: The workspace's pinned SKUs in their new order.

        Returns:
            The full pinned list in its new order.

        Raises:
            ValidationError: The list is not exactly the current pinned set.
        """
        rows = await self._pinned_skus.list_rows(workspace_id=workspace_id)
        current = {row.nm_id for row in rows}
        if set(nm_ids) != current:
            raise ValidationError(
                "The pinned SKU list changed — refresh the page and reorder again."
            )
        await self._pinned_skus.reorder(nm_ids=nm_ids)
        return await self.list_pinned_skus(workspace_id=workspace_id)

    async def set_sku_color(
        self, *, workspace_id: uuid.UUID, nm_id: int, color: str | None
    ) -> PinnedSkusResponse:
        """Paint one pinned chip, or clear its tint (idempotent both ways).

        A no-op when the SKU is not pinned: there is no chip to paint, and the
        returned list says so.

        Args:
            workspace_id: The caller's active workspace (scopes the returned
                list; the ``nm_id`` itself is ownership-guarded by the router).
            nm_id: WB SKU identifier.
            color: ``#rrggbb`` tint, or ``None`` to reset to the default chip.

        Returns:
            The full pinned list after the update.
        """
        await self._pinned_skus.set_color(nm_id=nm_id, color=color)
        return await self.list_pinned_skus(workspace_id=workspace_id)
