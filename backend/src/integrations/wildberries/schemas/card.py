"""Raw payload models for the public WB storefront card detail (card.wb.ru).

Storefront card detail — ``GET https://card.wb.ru/cards/v4/detail``.

Verified doc/community shape (2026-07): {"data": {"products": [ {"id": nmId,
"sizes": [ {"price": {"basic": .., "product": .., "total": ..}} ]} ]}}. Prices
are in KOPECKS. ``product`` is the final customer price after ALL discounts
(incl. WB loyalty / SPP); ``basic`` is before them. Unauthenticated endpoint.
"""

from __future__ import annotations

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBCardPrice(RawBase):
    """The nested ``price`` object of a storefront size (kopecks)."""

    basic: int = Field(default=0)
    product: int = Field(default=0)
    total: int = Field(default=0)


class WBCardSizePrice(RawBase):
    """One storefront size carrying its ``price`` block."""

    price: WBCardPrice = Field(default_factory=WBCardPrice)


class WBCardProduct(RawBase):
    """A storefront product node: nmId identity + per-size prices."""

    nm_id: int = Field(alias="id")
    sizes: list[WBCardSizePrice] = Field(default_factory=list)

    @property
    def customer_price(self) -> float | None:
        """Final customer price in rubles (kopecks/100), or ``None``.

        Uses the first size's ``product`` price (falling back to ``total``);
        storefront sizes of one card share the shown price.
        """
        for size in self.sizes:
            kopecks = size.price.product or size.price.total
            if kopecks > 0:
                return round(kopecks / 100, 2)
        return None
