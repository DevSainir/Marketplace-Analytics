"""The demo shop's days: a deterministic simulation every table is filled from.

Every figure is a pure function of the article (or campaign) and the CALENDAR
DATE — never of the day the seed happens to run. Re-seeding tomorrow therefore
adds a day and leaves every earlier day's numbers exactly as they were, which is
what a real shop's history does. Only what genuinely depends on "now" — whether
a day's orders have matured into buyouts yet — reads ``today``.

Tables are not consistent by accident: the funnel's opens include the ad
clicks, its orders include the ad orders, the settlement sells what the funnel
bought out, and the stock falls between supplies. A demo whose screens disagree
with each other would demonstrate the wrong thing.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from scripts.seed_demo.catalogue import CAMPAIGNS, DemoCampaign, DemoSku

#: Days of monitoring history (funnel, prices, ads) behind yesterday: a year, so
#: every long view — the heatmap by month, the labs' year chart — has one.
HISTORY_DAYS = 365

#: Days of stock history. The stock screen reads at most 62 days back.
STOCK_DAYS = 62

#: WB serves a day's buyouts and cancellations over the following week; a day
#: younger than this is shown as "not yet decided" (``cancel_count`` NULL).
MATURITY_DAYS = 7

#: Days between an order and the sale that settles it.
DELIVERY_LAG_DAYS = 3

#: Demand by weekday, Monday first: WB apparel peaks at the weekend.
_WEEKDAY = (1.02, 0.97, 0.95, 0.96, 1.0, 1.08, 1.12)

_CENT = Decimal("0.01")


def money(value: Decimal | float) -> Decimal:
    """Round to kopecks, half up — how WB rounds every amount it reports."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def draw(*key: object) -> random.Random:
    """A random stream fixed by ``key``, so a draw never changes between runs."""
    return random.Random(":".join(str(part) for part in key))  # noqa: S311 — reproducible fiction, not a secret


def noise(spread: float, *key: object) -> float:
    """A multiplicative wobble around 1 — ±``spread`` at one sigma, never negative."""
    return max(0.2, 1.0 + draw(*key).gauss(0.0, spread))


def _wave(day: date, period: int, phase: int = 0) -> float:
    """A slow seasonal swing in [-1, 1] with the given period in days."""
    return math.sin(2 * math.pi * (day.toordinal() + phase) / period)


def window(end: date, days: int) -> list[date]:
    """The ``days`` calendar days ending on ``end``, oldest first."""
    return [end - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


# --------------------------------------------------------------------- prices


def seller_price(sku: DemoSku, day: date) -> Decimal:
    """The seller's price: raised by a tenth for one month in every three."""
    raised = (day.toordinal() // 30 + sku.nm_id) % 3 == 0
    return sku.seller_price + (money(sku.seller_price / 10) // 10 * 10 if raised else 0)


def spp_percent(sku: DemoSku, day: date) -> Decimal:
    """WB's own customer discount, which it moves on its own schedule."""
    return Decimal(round(19 + 5 * _wave(day, 23, sku.nm_id % 17), 0))


def customer_price(sku: DemoSku, day: date) -> Decimal:
    """What the buyer pays: the seller's price less WB's discount, to whole roubles."""
    paid = seller_price(sku, day) * (1 - spp_percent(sku, day) / 100)
    return paid.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------------ ads


@dataclass(frozen=True)
class AdDay:
    """One campaign's day on one article."""

    campaign: DemoCampaign
    nm_id: int
    day: date
    views: int
    clicks: int
    carts: int
    orders: int
    spend: Decimal
    search_views: int
    search_clicks: int
    search_spend: Decimal


def campaign_runs(campaign: DemoCampaign, day: date, today: date) -> bool:
    """Whether a campaign spent on ``day``: from its start, with a pause each month."""
    started = day >= today - timedelta(days=campaign.first_day_ago)
    paused = (day.toordinal() + campaign.campaign_id) % 31 in (0, 1)
    return started and not paused


def ad_day(campaign: DemoCampaign, day: date) -> AdDay:
    """The campaign's day on its own article."""
    sku_noise = noise(0.14, "ads", campaign.campaign_id, day)
    views = round(campaign.views * _WEEKDAY[day.weekday()] * sku_noise)
    clicks = round(views * campaign.ctr * noise(0.1, "ctr", campaign.campaign_id, day))
    carts = round(clicks * 0.11)
    orders = round(clicks * 0.034 * noise(0.25, "ad-orders", campaign.campaign_id, day))
    if campaign.payment_type == "cpc":
        spend = money(Decimal(clicks) * campaign.rate)
    else:
        spend = money(Decimal(views) * campaign.rate / 1000)
    share = campaign.search_share
    return AdDay(
        campaign=campaign,
        nm_id=campaign.nm_id,
        day=day,
        views=views,
        clicks=clicks,
        carts=carts,
        orders=orders,
        spend=spend,
        search_views=round(views * share),
        search_clicks=round(clicks * share),
        search_spend=money(spend * Decimal(str(share))),
    )


def companion_orders(campaign: DemoCampaign, day: date) -> int:
    """Orders a campaign's traffic brings the article shown next to its own."""
    return 1 if draw("companion", campaign.campaign_id, day).random() < 0.45 else 0


def ad_days(day: date, today: date) -> list[AdDay]:
    """Every campaign's day on its own article, for campaigns running that day."""
    return [ad_day(c, day) for c in CAMPAIGNS if campaign_runs(c, day, today)]


# --------------------------------------------------------------------- funnel


@dataclass(frozen=True)
class FunnelDay:
    """One article's card funnel for one day, matured or not."""

    sku: DemoSku
    day: date
    opens: int
    carts: int
    orders: int
    wishlist: int
    buyouts: int
    cancels: int | None


def final_outcome(sku: DemoSku, day: date, orders: int) -> tuple[int, int]:
    """How a day's orders end once WB has decided all of them: (bought, cancelled)."""
    rate = sku.buyout_rate * noise(0.06, "buyout", sku.nm_id, day)
    bought = min(orders, round(orders * rate))
    return bought, orders - bought


def demand(sku: DemoSku, day: date, today: date) -> tuple[int, int, int]:
    """A day's (opens, carts, orders): organic demand plus what the campaigns brought.

    ``today`` only decides which campaigns had started by ``day``.
    """
    swing = (
        _WEEKDAY[day.weekday()]
        * (1 + 0.18 * _wave(day, 61, sku.nm_id % 29))
        * noise(0.11, "opens", sku.nm_id, day)
    )
    opens = round(sku.opens * swing)
    carts = round(opens * sku.cart_rate * noise(0.08, "carts", sku.nm_id, day))
    orders = round(carts * sku.order_rate * noise(0.12, "orders", sku.nm_id, day))
    for ad in ad_days(day, today):
        if ad.nm_id == sku.nm_id:
            opens += ad.clicks
            carts += ad.carts
            orders += ad.orders
    for campaign in CAMPAIGNS:
        if campaign.companion == sku.nm_id and campaign_runs(campaign, day, today):
            orders += companion_orders(campaign, day)
    return opens, carts, orders


def funnel_day(sku: DemoSku, day: date, today: date) -> FunnelDay:
    """One article's funnel, with buyouts only as far as WB has decided them."""
    opens, carts, orders = demand(sku, day, today)
    wishlist = round(opens * 0.021)
    bought, cancelled = final_outcome(sku, day, orders)
    age = (today - day).days
    if age >= MATURITY_DAYS:
        return FunnelDay(sku, day, opens, carts, orders, wishlist, bought, cancelled)
    # Not yet decided: some buyouts are in, and WB has not answered the rest.
    partial = bought * max(age, 0) // MATURITY_DAYS
    return FunnelDay(sku, day, opens, carts, orders, wishlist, partial, None)


# ---------------------------------------------------------------------- stock


def stock_units(sku: DemoSku, day: date) -> int:
    """Units on WB's warehouses: a supply every two weeks, sold down in between."""
    cycle = 14
    since_supply = (day.toordinal() + sku.nm_id) % cycle
    left = 1.0 - 0.72 * since_supply / (cycle - 1)
    return max(0, round(sku.stock * left * noise(0.03, "stock", sku.nm_id, day)))


# ----------------------------------------------------------------- settlement


@dataclass(frozen=True)
class SaleDay:
    """What the settlement records for one article on one day."""

    sku: DemoSku
    day: date
    order_day: date
    sold: int
    returned: int
    cancelled: int


def sale_day(sku: DemoSku, day: date, today: date) -> SaleDay:
    """Sales settled on ``day``: the buyouts of the orders placed a few days before.

    The order day's outcome is taken as FINAL whatever its age — the settlement
    only ever covers days well past the funnel's maturity window anyway.
    """
    order_day = day - timedelta(days=DELIVERY_LAG_DAYS)
    orders = demand(sku, order_day, today)[2]
    bought, cancelled = final_outcome(sku, order_day, orders)
    returned = sum(
        1 for unit in range(bought) if draw("return", sku.nm_id, day, unit).random() < 0.035
    )
    return SaleDay(sku, day, order_day, bought, returned, cancelled)
