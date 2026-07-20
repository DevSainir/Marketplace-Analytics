"""Raw payload models for the WB Content surface (product cards).

Content — product cards: ``POST /content/v2/get/cards/list``.

Verified live shape (2026-07): {"cards": [ {nmID, vendorCode, title,
brand, sizes: [{chrtID, techSize, wbSize, skus}], ...}, ... ],
"cursor": {updatedAt, nmID, total}}. This is the authoritative source for
the human-readable vendor code (``Артикул продавца``) and size label
(``Размер вещи`` == ``techSize``); the stocks endpoint carries only chrtID.
"""

from __future__ import annotations

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBCardSize(RawBase):
    """One size variant of a product card.

    ``tech_size`` is WB's human size label (the seller-portal "Размер вещи"
    column, e.g. ``"52/170-177"`` / ``"L"`` / ``"42"``); ``wb_size`` is WB's
    alternate scale (e.g. ``"2XL/ 170-177"`` / ``"46"``). ``chrt_id`` is the
    join key back to the label-less stock rows.
    """

    chrt_id: int = Field(alias="chrtID")
    tech_size: str = Field(default="", alias="techSize")
    wb_size: str = Field(default="", alias="wbSize")


class WBCard(RawBase):
    """A product card: nmID identity, seller vendor code, title, and sizes."""

    nm_id: int = Field(alias="nmID")
    vendor_code: str = Field(default="", alias="vendorCode")
    title: str = Field(default="", alias="title")
    sizes: list[WBCardSize] = Field(default_factory=list)
