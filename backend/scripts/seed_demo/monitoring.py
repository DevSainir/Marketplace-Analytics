"""The demo's catalogue and daily monitoring facts: cards, funnel, prices, stock, sales.

Monitoring tables carry no tenant column of their own — every read reaches them
through ``product_card.workspace_id`` — so the cards are what make the rest of
this module's rows belong to the demo workspace.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import (
    BRAND,
    CAMPAIGNS,
    CURRENCY,
    SKUS,
    WAREHOUSES,
    DemoSku,
    barcode,
    chrt_id,
    size_weight,
)
from scripts.seed_demo.economics import sale_amounts
from scripts.seed_demo.writes import insert_rows
from src.modules.monitoring.models import (
    PinnedSku,
    PriceSnapshot,
    ProductCard,
    ProductSize,
    SaleRecord,
    SalesFunnelDaily,
    SkuDayAction,
    SkuDayComment,
    StockSnapshot,
)

#: Days of the statistics feed (``sale_record``) behind yesterday.
_SALE_FEED_DAYS = 60

#: Two pinned articles, painted in the first two colours of the pin palette
#: (``frontend/src/modules/monitoring/pinColors.js``).
_PINS: tuple[tuple[int, str], ...] = ((SKUS[0].nm_id, "#E3DEFF"), (SKUS[3].nm_id, "#D3E8DE"))


def _percent(part: int, whole: int) -> Decimal:
    """``part`` as a percentage of ``whole``, to two places; zero when there is no whole."""
    return Decimal(0) if not whole else sim.money(Decimal(part) * 100 / whole)


def card_rows(workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    """One card per article, owned by the demo workspace. No photo: see the catalogue."""
    return [
        {
            "nm_id": sku.nm_id,
            "workspace_id": workspace_id,
            "vendor_code": sku.vendor_code,
            "title": sku.title,
            "photo_url": "",
            "subject_name": sku.subject,
            "brand": BRAND,
            "feedback_rating": Decimal("4.9") - Decimal(index % 4) / 10,
        }
        for index, sku in enumerate(SKUS)
    ]


def size_rows() -> list[dict[str, Any]]:
    """Every size of every article, with its WB size id and barcode."""
    return [
        {
            "chrt_id": chrt_id(sku, index),
            "nm_id": sku.nm_id,
            "tech_size": size,
            "wb_size": size,
            "barcode": barcode(sku, index),
        }
        for sku in SKUS
        for index, size in enumerate(sku.sizes)
    ]


def funnel_rows(today: date) -> list[dict[str, Any]]:
    """The card funnel for every article, up to yesterday — WB serves it a day late."""
    rows: list[dict[str, Any]] = []
    for day in sim.window(today - timedelta(days=1), sim.HISTORY_DAYS):
        for sku in SKUS:
            facts = sim.funnel_day(sku, day, today)
            price = sim.customer_price(sku, day)
            rows.append(
                {
                    "stat_date": day,
                    "nm_id": sku.nm_id,
                    "open_count": facts.opens,
                    "cart_count": facts.carts,
                    "order_count": facts.orders,
                    "buyout_count": facts.buyouts,
                    "cancel_count": facts.cancels,
                    "add_to_wishlist": facts.wishlist,
                    "order_sum": price * facts.orders,
                    "buyout_sum": price * facts.buyouts,
                    "cancel_sum": None if facts.cancels is None else price * facts.cancels,
                    "currency": CURRENCY,
                    "cart_conversion": _percent(facts.carts, facts.opens),
                    "order_conversion": _percent(facts.orders, facts.carts),
                    "buyout_conversion": _percent(facts.buyouts, facts.orders),
                }
            )
    return rows


def price_rows(today: date) -> list[dict[str, Any]]:
    """One price snapshot per article per day, today included."""
    return [
        {
            "stat_date": day,
            "nm_id": sku.nm_id,
            "seller_price": sim.seller_price(sku, day),
            "customer_price": sim.customer_price(sku, day),
            "customer_spp": sim.spp_percent(sku, day),
            "customer_source": "storefront",
            "currency": CURRENCY,
        }
        for day in sim.window(today, sim.HISTORY_DAYS + 1)
        for sku in SKUS
    ]


def stock_rows(today: date) -> list[dict[str, Any]]:
    """Stock per article, size and warehouse for every day of the stock window."""
    rows: list[dict[str, Any]] = []
    for day in sim.window(today, sim.STOCK_DAYS):
        for sku in SKUS:
            total = sim.stock_units(sku, day)
            for warehouse, region, share in WAREHOUSES:
                for index in range(len(sku.sizes)):
                    units = total * share * size_weight(sku, index)
                    rows.append(
                        {
                            "stat_date": day,
                            "nm_id": sku.nm_id,
                            "warehouse_name": warehouse,
                            "chrt_id": chrt_id(sku, index),
                            "region_name": region,
                            "quantity": round(units),
                            "in_way_to_client": round(units * 0.06),
                            "in_way_from_client": round(units * 0.015),
                        }
                    )
    return rows


def _sale_record(sku: DemoSku, sale: sim.SaleDay, unit: int, *, is_return: bool) -> dict[str, Any]:
    """One line of WB's statistics feed: a sale, or a return of one."""
    amounts = sale_amounts(sku, sale.order_day)
    prefix = "R" if is_return else "S"
    return {
        "sale_id": f"{prefix}{sku.nm_id}{sale.day:%y%m%d}{unit:03d}",
        "srid": f"demo.{sku.nm_id}.{sale.day:%Y%m%d}.{unit}",
        "nm_id": sku.nm_id,
        "sale_date": sale.day,
        "is_return": is_return,
        "finished_price": amounts.paid,
        "price_with_disc": amounts.seller_price,
        "for_pay": amounts.payout,
        "last_change_date": datetime.combine(sale.day, time(hour=12)),
    }


def sale_record_rows(today: date) -> list[dict[str, Any]]:
    """WB's statistics feed: every sale and return of the last two months."""
    rows: list[dict[str, Any]] = []
    for day in sim.window(today - timedelta(days=1), _SALE_FEED_DAYS):
        for sku in SKUS:
            sale = sim.sale_day(sku, day, today)
            rows.extend(_sale_record(sku, sale, unit, is_return=False) for unit in range(sale.sold))
            rows.extend(
                _sale_record(sku, sale, unit, is_return=True) for unit in range(sale.returned)
            )
    return rows


def annotation_rows(today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The seller's own marks in the matrix: every price change, and a campaign launch.

    Returns:
        ``(comments, actions)`` rows, at most one of each per article and day —
        that is the tables' key — and with identical keys so each is one INSERT.
    """
    comments: dict[tuple[int, date], dict[str, Any]] = {}
    actions: dict[tuple[int, date], dict[str, Any]] = {}

    def comment(nm_id: int, day: date, header: str, body: str) -> None:
        row = comments.setdefault(
            (nm_id, day), {"nm_id": nm_id, "comment_date": day, "header": header, "body": ""}
        )
        row["body"] = f"{row['body']}\n{body}".strip()

    def action(nm_id: int, day: date, **fields: Any) -> None:
        row = actions.setdefault(
            (nm_id, day),
            {
                "nm_id": nm_id,
                "action_date": day,
                "first_rk_type": None,
                "first_rk_budget": None,
                "price_change": None,
                "price_change_amount": None,
            },
        )
        row.update(fields)

    days = sim.window(today, sim.HISTORY_DAYS)
    for sku in SKUS:
        for previous, day in itertools.pairwise(days):
            before, after = sim.seller_price(sku, previous), sim.seller_price(sku, day)
            if before == after:
                continue
            direction = "up" if after > before else "down"
            header = "Price ↑" if direction == "up" else "Price ↓"
            comment(sku.nm_id, day, header, f"Seller price ₽{before:,.0f} → ₽{after:,.0f}")
            action(sku.nm_id, day, price_change=direction, price_change_amount=abs(after - before))

    launch = CAMPAIGNS[-1]
    launch_day = today - timedelta(days=launch.first_day_ago)
    comment(launch.nm_id, launch_day, "Campaign start", f'Launched "{launch.name}"')
    action(launch.nm_id, launch_day, first_rk_type="uni", first_rk_budget=Decimal("900"))
    return list(comments.values()), list(actions.values())


async def seed_monitoring(session: AsyncSession, workspace_id: uuid.UUID, today: date) -> int:
    """Write the catalogue and every daily monitoring fact. Returns rows written."""
    comments, actions = annotation_rows(today)
    pins = [
        {"nm_id": nm_id, "sort_order": order, "color": color, "created_at": datetime.now(UTC)}
        for order, (nm_id, color) in enumerate(_PINS)
    ]
    written = 0
    written += await insert_rows(session, ProductCard, card_rows(workspace_id))
    written += await insert_rows(session, ProductSize, size_rows())
    written += await insert_rows(session, SalesFunnelDaily, funnel_rows(today))
    written += await insert_rows(session, PriceSnapshot, price_rows(today))
    written += await insert_rows(session, StockSnapshot, stock_rows(today))
    written += await insert_rows(session, SaleRecord, sale_record_rows(today))
    written += await insert_rows(session, PinnedSku, pins)
    written += await insert_rows(session, SkuDayComment, comments)
    written += await insert_rows(session, SkuDayAction, actions)
    return written
