"""Pure assembly of the «Реклама» page from campaign-grain facts.

No I/O: the service loads, this cuts. Every cut — days, zones, articles, the
headline — is built from the same campaign-day rows, and the bonus reaches each
of them through the same placement (``bonus.py``), so the four agree to the
kopeck. That property is what the unit tests pin.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from src.modules.advertising.schemas import (
    AdvertisingDay,
    AdvertisingSku,
    AdvertisingTotals,
    AdvertisingZone,
    Zone,
)
from src.modules.advertising.services.bonus import place_bonus, split_by_weight
from src.modules.advertising.services.zones import zone_legs
from src.modules.monitoring.contract import AdCampaignFacts, CatalogCard

_ZERO = Decimal(0)


class SaleDay(NamedTuple):
    """One article's settled sales on one day (sales minus returns, seller's price)."""

    nm_id: int
    day: date
    sales: Decimal


class Composed(NamedTuple):
    """The page's four cuts."""

    totals: AdvertisingTotals
    zones: list[AdvertisingZone]
    days: list[AdvertisingDay]
    skus: list[AdvertisingSku]


class _CampaignDay(NamedTuple):
    campaign_id: int
    day: date


def compose(
    facts: AdCampaignFacts,
    *,
    sales: Iterable[SaleDay],
    settled_to: date | None,
    catalog: Iterable[CatalogCard],
    orders: dict[int, int] | None,
) -> Composed:
    """Cut the window's facts into totals, zones, days and articles.

    Args:
        facts: Campaign-grain advertising of the кабинет for the window.
        sales: Settled sales per article-day; empty when nothing settled.
        settled_to: Last settled day; spend after it has no sales to divide by.
        catalog: The кабинет's cards, for article labels.
        orders: Ordered units per article over the window, or ``None`` when the
            funnel does not cover it (then every article's orders are unknown).
    """
    # Campaign-day spend, per article and in total — the grain every cut sums.
    by_nm: dict[_CampaignDay, dict[int, Decimal]] = defaultdict(dict)
    for row in facts.spend:
        key = _CampaignDay(row.campaign_id, row.stat_date)
        by_nm[key][row.nm_id] = by_nm[key].get(row.nm_id, _ZERO) + row.spend
    spend_cd = {key: sum(parts.values(), _ZERO) for key, parts in by_nm.items()}

    bonus_cd = _place_campaign_bonus(facts, spend_cd)
    search_cd = {_CampaignDay(row.campaign_id, row.stat_date): row.spend for row in facts.search}
    meta = {row.campaign_id: row for row in facts.campaigns}

    zone_spend: dict[Zone, Decimal] = defaultdict(lambda: _ZERO)
    zone_bonus: dict[Zone, Decimal] = defaultdict(lambda: _ZERO)
    day_spend: dict[date, Decimal] = defaultdict(lambda: _ZERO)
    day_bonus: dict[date, Decimal] = defaultdict(lambda: _ZERO)
    nm_spend: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    nm_bonus: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    nm_settled: dict[int, Decimal] = defaultdict(lambda: _ZERO)

    for key, spend in spend_cd.items():
        bonus = bonus_cd.get(key, _ZERO)
        day_spend[key.day] += spend
        day_bonus[key.day] += bonus

        legs = zone_legs(meta.get(key.campaign_id), spend, search_cd.get(key))
        weights = dict(legs)
        for zone, amount in legs:
            zone_spend[zone] += amount
        for zone, part in split_by_weight(bonus, weights).items():
            zone_bonus[zone] += part

        settled = settled_to is not None and key.day <= settled_to
        for nm_id, amount in by_nm[key].items():
            nm_spend[nm_id] += amount
            if settled:
                nm_settled[nm_id] += amount
        for nm_id, part in split_by_weight(bonus, by_nm[key]).items():
            nm_bonus[nm_id] += part

    sales_by_nm: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    sales_by_day: dict[date, Decimal] = defaultdict(lambda: _ZERO)
    for cell in sales:
        sales_by_nm[cell.nm_id] += cell.sales
        sales_by_day[cell.day] += cell.sales

    has_sales = settled_to is not None
    totals = AdvertisingTotals(
        spend=sum(day_spend.values(), _ZERO),
        bonus=sum(day_bonus.values(), _ZERO),
        spend_settled=sum(nm_settled.values(), _ZERO),
        sales=sum(sales_by_nm.values(), _ZERO) if has_sales else None,
    )
    zones = [
        AdvertisingZone(zone=zone, spend=zone_spend[zone], bonus=zone_bonus.get(zone, _ZERO))
        for zone in sorted(zone_spend)
        if zone_spend[zone]
    ]
    days = [
        AdvertisingDay(
            day=day,
            spend=day_spend.get(day, _ZERO),
            bonus=day_bonus.get(day, _ZERO),
            sales=(
                sales_by_day.get(day, _ZERO)
                if settled_to is not None and day <= settled_to
                else None
            ),
        )
        for day in sorted(set(day_spend) | set(sales_by_day))
    ]
    cards = {card.nm_id: card for card in catalog}
    skus = [
        _sku_row(
            nm_id,
            cards.get(nm_id),
            spend=nm_spend.get(nm_id, _ZERO),
            bonus=nm_bonus.get(nm_id, _ZERO),
            settled=nm_settled.get(nm_id, _ZERO),
            sales=sales_by_nm.get(nm_id, _ZERO) if has_sales else None,
            orders=None if orders is None else orders.get(nm_id, 0),
        )
        for nm_id in sorted(set(nm_spend) | set(sales_by_nm))
        if nm_spend.get(nm_id) or sales_by_nm.get(nm_id)
    ]
    return Composed(totals=totals, zones=zones, days=days, skus=skus)


def _place_campaign_bonus(
    facts: AdCampaignFacts, spend_cd: dict[_CampaignDay, Decimal]
) -> dict[_CampaignDay, Decimal]:
    """Place each campaign's charged bonus on its own spend days (see ``place_bonus``)."""
    spend_days: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for key, spend in spend_cd.items():
        spend_days[key.campaign_id][key.day] = spend
    charged: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for row in facts.bonus:
        days = charged[row.campaign_id]
        days[row.stat_date] = days.get(row.stat_date, _ZERO) + row.amount

    out: dict[_CampaignDay, Decimal] = {}
    for campaign_id, charges in charged.items():
        placed = place_bonus(spend_days.get(campaign_id, {}), charges)
        for day, amount in placed.items():
            out[_CampaignDay(campaign_id, day)] = amount
    return out


def _sku_row(
    nm_id: int,
    card: CatalogCard | None,
    *,
    spend: Decimal,
    bonus: Decimal,
    settled: Decimal,
    sales: Decimal | None,
    orders: int | None,
) -> AdvertisingSku:
    """One article row; a card missing from the catalogue is labelled by its nm."""
    return AdvertisingSku(
        nm_id=nm_id,
        vendor_code=card.vendor_code if card and card.vendor_code else f"nm {nm_id}",
        subject=card.subject_name if card else "",
        brand=card.brand if card else "",
        spend=spend,
        bonus=bonus,
        spend_settled=settled,
        sales=sales,
        orders=orders,
    )
