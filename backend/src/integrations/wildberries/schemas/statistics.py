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


class WBOrderPrice(RawBase):
    """One ordered line, read ONLY for the price a customer was charged.

    Deliberately not a resurrection of the removed ``supplier/orders`` feed
    (``f624c17``): that fed an order LINE, counted 10-15 % below the funnel for
    the same days, and its table was dropped because nothing read it. The
    objection was to the count, not to the money in the row — so this model
    carries the money and the two things needed to place it, and nothing else.
    No table, no series, no screen: these rows exist for the length of one
    harvest and end up as one price snapshot column.

    ``date`` is the ORDER date, which is why this feed and not ``supplier/sales``
    answers "what was the price on day D": a sale row is dated by the day the
    customer accepted the parcel, days after the price that was actually charged
    (measured 2026-09-22 — a sale-dated price matches the storefront snapshot in
    3,7 % of day x SKU pairs against the order-dated 31,4 %, and covered 3 SKUs
    of 359 on the day).

    ``spp`` is WB's loyalty discount as a whole-number percent, and it is
    REGIONAL: within one day and one SKU it is a single value in 87,6 % of
    regions but only 27,1 % of the time across them, so ``region_name`` travels
    with it (measured 2026-09-22 on 3901 rows).
    """

    srid: str
    nm_id: int = Field(alias="nmId")
    ordered_at: datetime = Field(alias="date")
    last_change_date: datetime = Field(alias="lastChangeDate")
    is_cancel: bool = Field(default=False, alias="isCancel")
    #: What the customer was charged, WB's СПП already applied.
    finished_price: float = Field(default=0.0, alias="finishedPrice")
    #: The seller's own price after the seller's discount, before СПП.
    price_with_disc: float = Field(default=0.0, alias="priceWithDisc")
    #: WB's loyalty discount, whole-number percent (12 for a measured 12,4 %).
    spp: float = Field(default=0.0)
    #: Delivery region — the axis ``spp`` actually varies along.
    region_name: str = Field(default="", alias="regionName")


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
