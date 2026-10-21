"""Gathering one window's SKU-day facts from the modules that own them.

The heatmap owns no measurements. Funnel, advertising, prices and stock come
through the monitoring contract; revenue, units and payout through the
finreports one. This file turns their rows into :class:`~.metrics.Facts` keyed
by ``(nm_id, day)`` and asks each source only when a chosen metric reads it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.contract import PnlService, SkuReportService
from src.modules.heatmap.services.metrics import Facts, spread_bonus
from src.modules.monitoring.contract import (
    load_ad_bonus_by_nm,
    load_ad_sku_days,
    load_funnel_sku_days,
    load_orders_by_nm,
    load_price_sku_days,
    load_stock_sku_days,
)


@dataclass(slots=True)
class LoadedFacts:
    """Everything the grid is folded from."""

    facts: dict[tuple[int, date], Facts]
    #: Ordered units per article over the window — the default row order.
    rank: dict[int, int]
    currency: str
    settled_to: date | None


@dataclass(frozen=True, slots=True)
class FactsWindow:
    """What to load: whose, when, which sources, and optionally which articles."""

    workspace_id: uuid.UUID
    date_from: date
    date_to: date
    sources: frozenset[str]
    nm_ids: Collection[int] | None


async def load_facts(
    session: AsyncSession, window: FactsWindow, *, pnl: PnlService, skus: SkuReportService
) -> LoadedFacts:
    """Load the window's facts from every source the metrics need.

    Args:
        session: The request's session; the tenant is already bound on it.
        window: The workspace, the dates, the sources and the article narrowing.
        pnl: The P&L service — for the last settled day.
        skus: The per-SKU P&L service — for the settlement's per-day cut.
    """
    ws, start, end, narrow = window.workspace_id, window.date_from, window.date_to, window.nm_ids
    facts: dict[tuple[int, date], Facts] = {}

    def cell(nm_id: int, day: date) -> Facts:
        return facts.setdefault((nm_id, day), Facts())

    rank: dict[int, int] = {}
    if "funnel" in window.sources:
        for row in await load_funnel_sku_days(
            session, workspace_id=ws, date_from=start, date_to=end, nm_ids=narrow
        ):
            f = cell(row.nm_id, row.stat_date)
            f.funnel_days += 1
            f.opens += row.opens
            f.carts += row.carts
            f.orders += row.orders
            if row.amount_seller is not None:
                f.priced_orders += row.orders
                f.amount_seller += row.amount_seller
            if row.amount_paid is not None:
                f.paid_orders += row.orders
                f.amount_paid += row.amount_paid
            if row.order_value is not None and row.currency:
                f.valued_orders += row.orders
                f.order_value += row.order_value
                f.order_currencies = f.order_currencies | {row.currency}
            rank[row.nm_id] = rank.get(row.nm_id, 0) + row.orders
    else:
        rank = await load_orders_by_nm(session, workspace_id=ws, date_from=start, date_to=end)

    if "ads" in window.sources:
        for ad in await load_ad_sku_days(
            session, workspace_id=ws, date_from=start, date_to=end, nm_ids=narrow
        ):
            f = cell(ad.nm_id, ad.stat_date)
            f.ad_days += 1
            f.spend += ad.spend
            f.ad_views += ad.views
            f.ad_clicks += ad.clicks
            f.ad_orders += ad.orders
            f.ad_currencies = f.ad_currencies | frozenset(ad.currencies)

    if "prices" in window.sources:
        for price in await load_price_sku_days(
            session, workspace_id=ws, date_from=start, date_to=end, nm_ids=narrow
        ):
            f = cell(price.nm_id, price.stat_date)
            if price.seller_price is not None:
                f.seller_price_sum += price.seller_price
                f.seller_price_n += 1
            if price.customer_price is not None:
                f.customer_price_sum += price.customer_price
                f.customer_price_n += 1

    if "stock" in window.sources:
        for stock in await load_stock_sku_days(
            session, workspace_id=ws, date_from=start, date_to=end, nm_ids=narrow
        ):
            f = cell(stock.nm_id, stock.stat_date)
            f.stock = stock.quantity
            f.stock_date = stock.stat_date

    currency, settled_to = "", None
    if "finance" in window.sources:
        currency, settled_to = await _load_finance(window, cell, pnl=pnl, skus=skus)
        _mark_settled(facts, settled_to)
        if "ads" in window.sources and settled_to is not None:
            bonus = await load_ad_bonus_by_nm(
                session, workspace_id=ws, date_from=start, date_to=end
            )
            spread_bonus(facts, bonus)

    return LoadedFacts(facts=facts, rank=rank, currency=currency, settled_to=settled_to)


async def _load_finance(
    window: FactsWindow,
    cell: Callable[[int, date], Facts],
    *,
    pnl: PnlService,
    skus: SkuReportService,
) -> tuple[str, date | None]:
    """Fold the settlement's per-SKU-day cut in; return its currency and last settled day."""
    span = await pnl.get_settled_span(workspace_id=window.workspace_id)
    if span is None:
        return "", None
    settled = await skus.get_sku_days(
        workspace_id=window.workspace_id, date_from=window.date_from, date_to=window.date_to
    )
    wanted = None if window.nm_ids is None else set(window.nm_ids)
    for row in settled.cells:
        if wanted is not None and row.nm_id not in wanted:
            continue
        f = cell(row.nm_id, row.day)
        f.revenue += row.revenue_seller
        f.sold_units += row.sold_units - row.returned_units
        f.payout_net += row.payout_net
        if row.cogs is None:
            f.uncosted = f.uncosted or bool(row.sold_units or row.returned_units)
        else:
            f.cogs += row.cogs
    return settled.currency, span[1]


def _mark_settled(facts: dict[tuple[int, date], Facts], settled_to: date | None) -> None:
    """Make every settled SKU-day a known zero, and charge its ads against its profit."""
    if settled_to is None:
        return
    for (_, day), f in facts.items():
        if day <= settled_to:
            f.finance_known = True
            f.settled_spend = f.spend
