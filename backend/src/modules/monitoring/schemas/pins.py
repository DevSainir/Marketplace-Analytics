"""DTOs for the global pinned-SKU list («Закрепить»)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PinnedSkuItem(BaseModel):
    """One pinned SKU, decorated with its catalogue identity for the chip row.

    ``vendor_code``/``title`` are ``None`` when the catalogue has not been
    synced for the SKU yet — the chip then falls back to the raw ``nm_id``.
    """

    nm_id: int = Field(description="WB SKU identifier.")
    vendor_code: str | None = Field(default=None, description="Seller article code.")
    title: str | None = Field(default=None, description="Product card title.")


class PinnedSkusResponse(BaseModel):
    """The global pinned-SKU list, in pin order (oldest pin first)."""

    items: list[PinnedSkuItem] = Field(default_factory=list)


class PinUpdateRequest(BaseModel):
    """Body of the pin endpoint: the desired pinned state."""

    pinned: bool = Field(description="True to pin the SKU, false to unpin.")
