"""DTOs of the «Реклама» page.

Money is a ``Decimal`` in the response's ``currency``. ``None`` and ``0`` stay
apart everywhere: ``sales`` is ``None`` for a day or article the settlement has
not reached yet, which is «ещё не рассчитано», not «продаж не было».

ДРР is deliberately NOT a field. Every row carries the figures it is divided
from — ``spend_settled - bonus_settled`` over ``sales`` — so the page can
re-derive it for a group or a filter from summed money, never as a mean of
ratios.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

#: The «На что ушли» buckets — see ``services/zones.py`` for which campaign lands where.
Zone = Literal[
    "cpm_manual_search",
    "cpm_manual_catalog",
    "cpm_manual_shelves",
    "cpm_unified_search",
    "cpm_unified_shelves",
    "cpc_search",
    "cpc_shelves",
    "unclassified",
]


class AdvertisingSpan(BaseModel):
    """The days the кабинет has advertising for, for the period picker."""

    date_from: date | None
    date_to: date | None
    #: The last day the settlement covers — where «ДРР от продаж» stops.
    settled_to: date | None


class AdvertisingTotals(BaseModel):
    """The window's headline figures."""

    #: Everything ``fullstats`` booked, whoever paid for it.
    spend: Decimal
    #: The part WB's bonus pool paid («Кэшбэк» in the ledger).
    bonus: Decimal
    #: Spend on the days the settlement covers.
    spend_settled: Decimal
    #: WB's bonus on those same days. ДРР's numerator is
    #: ``spend_settled - bonus_settled``: the seller's own money.
    bonus_settled: Decimal
    #: Sales minus returns at the seller's price, over the settled days.
    sales: Decimal | None


class AdvertisingZone(BaseModel):
    """One display zone's money; zones with no spend are omitted."""

    zone: Zone
    spend: Decimal
    bonus: Decimal


class AdvertisingDay(BaseModel):
    """One day of the window."""

    day: date
    spend: Decimal
    bonus: Decimal
    #: ``None`` past the settled span.
    sales: Decimal | None


class AdvertisingSkuZone(BaseModel):
    """One article's money in one display zone — the row's breakdown.

    The campaign-day's zone split (``services/zones.py``) applied to the
    article's part of that campaign-day: an article that took 40 % of a
    campaign's day takes 40 % of each of its zones. normquery does carry an
    article, but a campaign-day split per article from it would send all of
    an article's spend to «Поиск» whenever it had no search row of its own.
    """

    zone: Zone
    spend: Decimal
    bonus: Decimal


class AdvertisingSku(BaseModel):
    """One article that advertised or sold in the window."""

    nm_id: int
    vendor_code: str
    subject: str
    brand: str
    spend: Decimal
    bonus: Decimal
    spend_settled: Decimal
    bonus_settled: Decimal
    sales: Decimal | None
    #: Ordered units from WB's funnel; ``None`` when the funnel does not cover the window.
    orders: int | None
    #: The row's spend and bonus by display zone; sums to ``spend`` and ``bonus``
    #: exactly. Zones the article did not run in are omitted.
    zones: list[AdvertisingSkuZone] = []


class AdvertisingResponse(BaseModel):
    """Every figure the page draws for one window."""

    date_from: date
    date_to: date
    settled_to: date | None
    #: The unit of every money field.
    currency: str
    #: The currencies the window's ad spend was billed in. More than one, or one
    #: other than ``currency``, means ДРР would divide unlike units — the page
    #: then withholds it.
    ad_currencies: list[str]
    #: Whether WB's funding ledger covers the window at all: without it a zero
    #: bonus means «не знаем», not «WB ничего не оплатил».
    bonus_known: bool
    totals: AdvertisingTotals
    zones: list[AdvertisingZone]
    days: list[AdvertisingDay]
    skus: list[AdvertisingSku]
