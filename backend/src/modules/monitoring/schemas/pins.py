"""DTOs for the global pinned-SKU list ("Pin")."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.core.exceptions import UserInputError
from src.modules.monitoring.constants import MAX_NM_IDS_PER_REQUEST

# Chip tints are stored and exchanged as ``#rrggbb``. The palette itself lives
# in the frontend — the API only guarantees the shape, so the palette can be
# retuned without a migration.
COLOR_PATTERN: str = r"^#[0-9a-fA-F]{6}$"


class PinnedSkuItem(BaseModel):
    """One pinned SKU, decorated with its catalogue identity for the chip row.

    ``vendor_code``/``title`` are ``None`` when the catalogue has not been
    synced for the SKU yet — the chip then falls back to the raw ``nm_id``.
    """

    nm_id: int = Field(description="WB SKU identifier.")
    vendor_code: str | None = Field(default=None, description="Seller article code.")
    title: str | None = Field(default=None, description="Product card title.")
    color: str | None = Field(
        default=None, description="Chip tint as #rrggbb, or null when unpainted."
    )


class PinnedSkusResponse(BaseModel):
    """The global pinned-SKU list, in chip-row order."""

    items: list[PinnedSkuItem] = Field(default_factory=list)


class PinUpdateRequest(BaseModel):
    """Body of the pin endpoint: the desired pinned state."""

    pinned: bool = Field(description="True to pin the SKU, false to unpin.")


class PinColorUpdateRequest(BaseModel):
    """Body of the chip-colour endpoint: the desired tint."""

    color: str | None = Field(
        default=None,
        pattern=COLOR_PATTERN,
        description="Chip tint as #rrggbb, or null to clear it.",
    )


class PinReorderRequest(BaseModel):
    """Body of the reorder endpoint: the chip row's new left-to-right order."""

    nm_ids: list[int] = Field(
        max_length=MAX_NM_IDS_PER_REQUEST,
        description="Pinned SKU identifiers in their new order.",
    )

    @field_validator("nm_ids")
    @classmethod
    def _reject_duplicates(cls, value: list[int]) -> list[int]:
        """Reject a repeated ``nm_id``, which has no single position."""
        if len(set(value)) != len(value):
            raise UserInputError("SKUs must not repeat.")
        return value
