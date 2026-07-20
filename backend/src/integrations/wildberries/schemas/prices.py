"""Raw payload models for the WB Prices & Discounts surface (seller prices).

Prices & Discounts — ``GET /api/v2/list/goods/filter``.

Verified doc shape (2026-07): {"data": {"listGoods": [ {"nmID": ..,
"vendorCode": .., "sizes": [ {"sizeID": .., "price": .., "discountedPrice": ..,
"clubDiscountedPrice": .., "techSizeName": ..} ], "discount": ..,
"clubDiscount": ..} ]}}. ``discountedPrice`` is the price AFTER the seller's
own discount — the value the СПП and order/buyout ₽ volumes are computed from.
Sizes normally share one price; we take a representative size.
"""

from __future__ import annotations

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBPriceSize(RawBase):
    """One size variant's pricing on a goods-filter record (rubles)."""

    price: float = Field(default=0.0)
    discounted_price: float = Field(default=0.0, alias="discountedPrice")


class WBPriceGood(RawBase):
    """A SKU's pricing record: identity + per-size prices and the discount."""

    nm_id: int = Field(alias="nmID")
    discount: int = Field(default=0)
    sizes: list[WBPriceSize] = Field(default_factory=list)

    @property
    def seller_price(self) -> float | None:
        """Representative discounted seller price, or ``None`` if unavailable.

        All sizes of a card normally carry the same price, so the first size
        with a positive ``discountedPrice`` represents the SKU.
        """
        for size in self.sizes:
            if size.discounted_price > 0:
                return size.discounted_price
        return None
