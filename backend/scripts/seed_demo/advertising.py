"""The demo's advertising: campaigns, their daily statistics, and what WB charged.

WB links a campaign to the articles it advertises only through the statistics
rows themselves — there is no join table — so a campaign "belongs" to the demo
workspace by spending on the demo's cards. The write-offs carry the same spend
split into money and bonus, which is what the P&L and the advertising page read
to tell paid advertising from WB's cashback.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import CAMPAIGNS, CURRENCY, SKU_BY_NM
from scripts.seed_demo.writes import insert_rows
from src.modules.monitoring.models import (
    BALANCE_PAYMENT_TYPE,
    CASHBACK_PAYMENT_TYPE,
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    Campaign,
)

#: WB's code for the auction campaigns every current campaign is (``type=9``),
#: and the "active" status — see ``WB_TYPE_LABELS`` / ``WB_STATUS_LABELS``.
_AUCTION_TYPE = 9
_ACTIVE = 9

#: The application the statistics are filed under. WB splits a day by app; one
#: is enough, since every reader sums across them.
_APP_TYPE = 1

#: Share of the spend WB charges in money; the rest is paid from its cashback.
_CASH_SHARE = Decimal("0.82")


def campaign_rows() -> list[dict[str, Any]]:
    """Every campaign, as WB's campaign list describes it."""
    return [
        {
            "campaign_id": campaign.campaign_id,
            "type": _AUCTION_TYPE,
            "status": _ACTIVE,
            "status_label": "active",
            "bid_type": campaign.bid_type,
            "placement_search": campaign.search,
            "placement_recommendations": campaign.shelves,
            "name": campaign.name,
            "payment_type": campaign.payment_type,
        }
        for campaign in CAMPAIGNS
    ]


def _stat(ad: sim.AdDay) -> dict[str, Any]:
    """One campaign's day on its own article."""
    price = sim.customer_price(SKU_BY_NM[ad.nm_id], ad.day)
    return {
        "stat_date": ad.day,
        "campaign_id": ad.campaign.campaign_id,
        "app_type": _APP_TYPE,
        "nm_id": ad.nm_id,
        "views": ad.views,
        "clicks": ad.clicks,
        "add_to_cart": ad.carts,
        "orders": ad.orders,
        "spend": ad.spend,
        "order_sum": price * ad.orders,
        "currency": CURRENCY,
    }


def stat_rows(today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Daily statistics up to yesterday, and their search-placement slice.

    Returns:
        ``(statistics, search slice)`` rows.
    """
    stats: list[dict[str, Any]] = []
    search: list[dict[str, Any]] = []
    for day in sim.window(today - timedelta(days=1), sim.HISTORY_DAYS):
        for ad in sim.ad_days(day, today):
            stats.append(_stat(ad))
            if ad.campaign.search:
                search.append(
                    {
                        "stat_date": day,
                        "campaign_id": ad.campaign.campaign_id,
                        "nm_id": ad.nm_id,
                        "views": ad.search_views,
                        "clicks": ad.search_clicks,
                        "add_to_cart": round(ad.carts * ad.campaign.search_share),
                        "orders": round(ad.orders * ad.campaign.search_share),
                        "spend": ad.search_spend,
                    }
                )
            companion = ad.campaign.companion
            orders = sim.companion_orders(ad.campaign, day) if companion else 0
            if companion and orders:
                # Shown nowhere, bought anyway: the article next to the advertised
                # one. WB reports it under the same campaign with no impressions.
                price = sim.customer_price(SKU_BY_NM[companion], day)
                stats.append(
                    {
                        **_stat(ad),
                        "nm_id": companion,
                        "views": 0,
                        "clicks": 0,
                        "add_to_cart": orders,
                        "orders": orders,
                        "spend": Decimal("0.00"),
                        "order_sum": price * orders,
                    }
                )
    return stats, search


def write_off_rows(today: date) -> list[dict[str, Any]]:
    """What WB charged each campaign each day: money and cashback, separately."""
    rows: list[dict[str, Any]] = []
    for day in sim.window(today - timedelta(days=1), sim.HISTORY_DAYS):
        for ad in sim.ad_days(day, today):
            cash = sim.money(ad.spend * _CASH_SHARE)
            for payment_type, amount in (
                (BALANCE_PAYMENT_TYPE, cash),
                (CASHBACK_PAYMENT_TYPE, ad.spend - cash),
            ):
                rows.append(
                    {
                        "stat_date": day,
                        "campaign_id": ad.campaign.campaign_id,
                        "payment_type": payment_type,
                        "currency": CURRENCY,
                        "amount": amount,
                        "write_offs": 1 + ad.views // 4000,
                    }
                )
    return rows


def cash_spend(day: date, today: date) -> Decimal:
    """Advertising paid in money on ``day`` — what the weekly report deducts."""
    return sum(
        (sim.money(ad.spend * _CASH_SHARE) for ad in sim.ad_days(day, today)), Decimal("0.00")
    )


async def seed_advertising(session: AsyncSession, today: date) -> int:
    """Write the campaigns, their statistics and their write-offs. Returns rows written."""
    stats, search = stat_rows(today)
    written = await insert_rows(session, Campaign, campaign_rows())
    written += await insert_rows(session, AdvertisingStatDaily, stats)
    written += await insert_rows(session, AdvertisingSearchStatDaily, search)
    written += await insert_rows(session, AdvertisingWriteOffDaily, write_off_rows(today))
    return written
