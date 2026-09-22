"""Raw payload models for the WB Statistics surface (per-sale records).

Statistics — sale-date attributed buyouts / returns:
``GET https://statistics-api.wildberries.ru/api/v1/supplier/sales``.

Verified live shape (2026-07): a flat list of per-item operations. ``saleID``
is prefixed ``S`` for a buyout (продажа) and ``R`` for a return (возврат);
``date`` is the operation's SALE date (when the customer accepted / returned
the item — NOT the order date), ``lastChangeDate`` drives incremental
pagination (``dateFrom`` filters on it with ``flag=0``). ``finishedPrice``
is what the customer actually paid (matches the portal's «Выкупили, ₽»).

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
