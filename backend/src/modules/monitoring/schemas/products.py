"""Product-catalogue lookup DTOs (vendor code -> SKU resolution)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkuLookupItem(BaseModel):
    """A single SKU matched by a vendor-code search."""

    nm_id: int = Field(description="WB SKU identifier.")
    vendor_code: str = Field(description="Seller article code (WB's vendor code).")
    title: str = Field(description="Product card title.")


class SkuLookupResponse(BaseModel):
    """Vendor-code search results, ordered by vendor code."""

    query: str = Field(description="The vendor-code fragment that was searched.")
    count: int = Field(description="Number of matching SKUs returned.")
    items: list[SkuLookupItem] = Field(default_factory=list)
