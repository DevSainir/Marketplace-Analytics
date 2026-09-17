"""Raw payload models for the WB Statistics surface (per-item order/sale records).

Statistics — sale-date attributed buyouts / returns:
``GET https://statistics-api.wildberries.ru/api/v1/supplier/sales``.

Verified live shape (2026-07): a flat list of per-item operations. ``saleID``
is prefixed ``S`` for a buyout (продажа) and ``R`` for a return (возврат);
``date`` is the operation's SALE date (when the customer accepted / returned
the item — NOT the order date), ``lastChangeDate`` drives incremental
pagination (``dateFrom`` filters on it with ``flag=0``). ``finishedPrice``
is what the customer actually paid (matches the portal's «Выкупили, ₽»).

Orders — order-date attributed lines:
``GET https://statistics-api.wildberries.ru/api/v1/supplier/orders``, the same
shape of feed and the same ``lastChangeDate`` pagination. It is the ONLY source
of orders older than the analytics funnel's window, which is why it exists here:
the funnel is what a кабинет has from the day we started harvesting it, and this
is what WB has had all along.

``srid`` identifies the order line and is what a row is keyed by; ``date`` is
when the order was placed; ``isCancel`` marks a line the customer cancelled
(``cancelDate`` says when). Both prices travel: ``priceWithDisc`` is the
seller's own price after the seller's discount, ``finishedPrice`` the one the
customer pays after WB's СПП — the same two bases every money figure on
«Сводка» offers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBSaleRecord(RawBase):
    """One per-item sale or return operation from the Statistics API."""

    sale_id: str = Field(alias="saleID")
    srid: str = Field(default="")
    nm_id: int = Field(alias="nmId")
    sold_at: datetime = Field(alias="date")
    last_change_date: datetime = Field(alias="lastChangeDate")
    price_with_disc: float = Field(default=0.0, alias="priceWithDisc")
    finished_price: float = Field(default=0.0, alias="finishedPrice")
    for_pay: float = Field(default=0.0, alias="forPay")

    @property
    def is_return(self) -> bool:
        """True for a return operation (``R``-prefixed ``saleID``)."""
        return self.sale_id.startswith("R")


class WBOrderRecord(RawBase):
    """One ordered item line from the Statistics API."""

    srid: str
    nm_id: int = Field(alias="nmId")
    ordered_at: datetime = Field(alias="date")
    last_change_date: datetime = Field(alias="lastChangeDate")
    #: The seller's price after the seller's own discount.
    price_with_disc: float = Field(default=0.0, alias="priceWithDisc")
    #: What the customer pays, WB's СПП applied.
    finished_price: float = Field(default=0.0, alias="finishedPrice")
    is_cancel: bool = Field(default=False, alias="isCancel")
    cancel_date: datetime | None = Field(default=None, alias="cancelDate")
