"""Workspace-wide per-SKU, per-day facts — the heatmap's raw material.

:mod:`.exports` answers "how much did each SKU do over the window" and
:mod:`.day_series` "how much did the whole account do on each day"; these answer
the product of the two, one row per SKU per day, for every SKU of a кабинет at
once. The heatmap paints that grid, and building it from the per-SKU detail
loaders would be one round trip per article — hundreds on a large кабинет.

Four loaders, one per source, rather than one wide join: a heatmap cell shows at
most two metrics, and each loader is called only when a chosen metric reads its
source. Stock is the expensive one (a row per warehouse per size per day), and a
view of orders should not pay for it.

The rules of :mod:`.exports` apply unchanged — module-level functions, caller
owns the transaction, and **every** query scoped by ``workspace_id`` through
:func:`~src.modules.monitoring.repos.base.workspace_sku_select`. The optional
``nm_ids`` narrows a query further and can never widen it: it is ANDed with the
semijoin, so a foreign article in the list simply matches nothing.

Advertising here is the SKU's own Promotion-API rows summed as reported, every
campaign included — what the кабинет actually spent. The monitoring matrix's
«Общая» column keeps only the campaigns its bucket attribution selected, so the
two can differ on a card with small side campaigns; this is the figure that
adds up to the кабинет's spend.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    BONUS_PAYMENT_TYPES,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    PriceSnapshot,
    ProductCard,
    SalesFunnelDaily,
    StockSnapshot,
)
from src.modules.monitoring.repos.base import workspace_sku_select


class CatalogCard(NamedTuple):
    """One card of the кабинет's catalogue, as a row label and a filter option."""

    nm_id: int
    vendor_code: str
    title: str
    #: WB CDN URL, ``""`` when the card has none.
    photo_url: str
    #: WB's «Предмет»; ``""`` until a catalogue sync has carried it.
    subject_name: str
    brand: str


class FunnelSkuDay(NamedTuple):
    """One SKU on one day of WB's sales funnel.

    ``amount_*`` are the day's orders valued at that same day's price snapshot
    — the matrix's «Заказы, ₽» — and ``None`` where the day was never priced:
    WB's funnel carries no money of its own, so an unpriced day has no value
    rather than a value of zero.
    """

    nm_id: int
    stat_date: date
    opens: int
    carts: int
    orders: int
    amount_seller: Decimal | None
    amount_paid: Decimal | None


class AdSkuDay(NamedTuple):
    """One SKU's advertising on one day, summed over its campaigns and platforms."""

    nm_id: int
    stat_date: date
    spend: Decimal
    views: int
    clicks: int
    orders: int


class PriceSkuDay(NamedTuple):
    """One SKU's price snapshot on one day."""

    nm_id: int
    stat_date: date
    #: Before WB's СПП (``discountedPrice``).
    seller_price: Decimal | None
    #: What a shopper pays, СПП applied; ``None`` when neither source answered.
    customer_price: Decimal | None


class StockSkuDay(NamedTuple):
    """One SKU's units on WB warehouses on one day, over every size and warehouse."""

    nm_id: int
    stat_date: date
    quantity: int


def _scoped(
    stmt: Select[Any], column: Any, workspace_id: uuid.UUID, nm_ids: Collection[int] | None
) -> Select[Any]:
    """AND the tenant semijoin — and the optional article narrowing — onto ``stmt``."""
    stmt = stmt.where(column.in_(workspace_sku_select(workspace_id)))
    if nm_ids is not None:
        stmt = stmt.where(column.in_(sorted(nm_ids)))
    return stmt


def _money(value: object) -> Decimal | None:
    """A nullable numeric column as a Decimal."""
    return None if value is None else Decimal(str(value))


async def load_workspace_catalog(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[CatalogCard]:
    """Return every card the кабинет owns, ordered by article.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The кабинет whose catalogue to read.
    """
    stmt = (
        select(
            ProductCard.nm_id,
            ProductCard.vendor_code,
            ProductCard.title,
            ProductCard.photo_url,
            ProductCard.subject_name,
            ProductCard.brand,
        )
        .where(ProductCard.workspace_id == workspace_id)
        .order_by(ProductCard.vendor_code, ProductCard.nm_id)
    )
    return [
        CatalogCard(
            nm_id=int(nm_id),
            vendor_code=vendor_code or "",
            title=title or "",
            photo_url=photo_url or "",
            subject_name=subject_name or "",
            brand=brand or "",
        )
        for nm_id, vendor_code, title, photo_url, subject_name, brand in (
            await session.execute(stmt)
        ).all()
    ]


async def load_funnel_sku_days(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
    nm_ids: Collection[int] | None = None,
) -> list[FunnelSkuDay]:
    """Return the funnel per SKU per day, each day valued at its own price.

    A SKU-day with no funnel row is ABSENT rather than zero — "we were not told"
    is not "nobody ordered", the same rule :func:`.load_order_days` keeps.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.
        nm_ids: Optional narrowing to these articles.
    """
    funnel = SalesFunnelDaily
    stmt = (
        select(
            funnel.nm_id,
            funnel.stat_date,
            funnel.open_count,
            funnel.cart_count,
            funnel.order_count,
            funnel.order_count * PriceSnapshot.seller_price,
            funnel.order_count * PriceSnapshot.customer_price,
        )
        .outerjoin(
            PriceSnapshot,
            (PriceSnapshot.nm_id == funnel.nm_id) & (PriceSnapshot.stat_date == funnel.stat_date),
        )
        .where(funnel.stat_date >= date_from, funnel.stat_date <= date_to)
    )
    stmt = _scoped(stmt, funnel.nm_id, workspace_id, nm_ids)
    return [
        FunnelSkuDay(
            nm_id=int(nm_id),
            stat_date=day,
            opens=int(opens or 0),
            carts=int(carts or 0),
            orders=int(orders or 0),
            amount_seller=_money(seller),
            amount_paid=_money(paid),
        )
        for nm_id, day, opens, carts, orders, seller, paid in (await session.execute(stmt)).all()
    ]


async def load_ad_sku_days(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
    nm_ids: Collection[int] | None = None,
) -> list[AdSkuDay]:
    """Return advertising per SKU per day, every campaign and platform summed.

    Summing over ``app_type`` is correct, not a double count: the rows are
    separate platforms under a four-column key. A SKU-day with no burn is absent.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.
        nm_ids: Optional narrowing to these articles.
    """
    ads = AdvertisingStatDaily
    stmt = (
        select(
            ads.nm_id,
            ads.stat_date,
            func.sum(ads.spend),
            func.sum(ads.views),
            func.sum(ads.clicks),
            func.sum(ads.orders),
        )
        .where(ads.stat_date >= date_from, ads.stat_date <= date_to)
        .group_by(ads.nm_id, ads.stat_date)
    )
    stmt = _scoped(stmt, ads.nm_id, workspace_id, nm_ids)
    return [
        AdSkuDay(
            nm_id=int(nm_id),
            stat_date=day,
            spend=_money(spend) or Decimal(0),
            views=int(views or 0),
            clicks=int(clicks or 0),
            orders=int(orders or 0),
        )
        for nm_id, day, spend, views, clicks, orders in (await session.execute(stmt)).all()
    ]


async def load_price_sku_days(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
    nm_ids: Collection[int] | None = None,
) -> list[PriceSkuDay]:
    """Return each SKU's price snapshot per day; a day never priced is absent.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.
        nm_ids: Optional narrowing to these articles.
    """
    stmt = select(
        PriceSnapshot.nm_id,
        PriceSnapshot.stat_date,
        PriceSnapshot.seller_price,
        PriceSnapshot.customer_price,
    ).where(PriceSnapshot.stat_date >= date_from, PriceSnapshot.stat_date <= date_to)
    stmt = _scoped(stmt, PriceSnapshot.nm_id, workspace_id, nm_ids)
    return [
        PriceSkuDay(
            nm_id=int(nm_id),
            stat_date=day,
            seller_price=_money(seller),
            customer_price=_money(customer),
        )
        for nm_id, day, seller, customer in (await session.execute(stmt)).all()
    ]


async def load_stock_sku_days(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
    nm_ids: Collection[int] | None = None,
) -> list[StockSkuDay]:
    """Return units on WB warehouses per SKU per day; a day with no snapshot is absent.

    Only ``quantity`` — what sits on the shelf. The in-transit legs are stock
    WB is moving, not stock a buyer can order today, which is what a heatmap of
    «Остатки» is read for.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.
        nm_ids: Optional narrowing to these articles.
    """
    stock = StockSnapshot
    stmt = (
        select(stock.nm_id, stock.stat_date, func.sum(stock.quantity))
        .where(stock.stat_date >= date_from, stock.stat_date <= date_to)
        .group_by(stock.nm_id, stock.stat_date)
    )
    stmt = _scoped(stmt, stock.nm_id, workspace_id, nm_ids)
    return [
        StockSkuDay(nm_id=int(nm_id), stat_date=day, quantity=int(quantity or 0))
        for nm_id, day, quantity in (await session.execute(stmt)).all()
    ]


async def load_price_currency(session: AsyncSession, *, workspace_id: uuid.UUID) -> str:
    """Return the currency WB stated for this кабинет's newest priced snapshot.

    Not the settlement's currency. «Демо» settles in KGS while its prices
    API answers RUB; the orders valued at those prices (``amount_*`` above) are
    in this currency too. ``""`` when no snapshot has recorded one yet.
    """
    stmt = (
        select(PriceSnapshot.currency)
        .where(
            PriceSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
            PriceSnapshot.currency != "",
        )
        .order_by(PriceSnapshot.stat_date.desc())
        .limit(1)
    )
    return str((await session.execute(stmt)).scalar_one_or_none() or "")


async def load_ad_currencies(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> list[str]:
    """Return the currencies WB billed this кабинет's own ad money in over the window.

    ``fullstats`` spend carries no currency; the write-off ledger does, and its
    label is the truth rather than decoration: matched document by document
    against the KGS settlement on 2026-09-28, «Демо»'s write-offs labelled
    RUB were settled at ~1.03-1.10x (converted) and those labelled KGS at exactly
    1.00. The account switched around 2026-08-20, so a window across that day
    answers both. Bonus rows are left out — they are WB's money, labelled KGS
    throughout, and say nothing about the account's own currency.

    Returns:
        The distinct labels, alphabetically; empty when the ledger has no rows.
    """
    campaigns = (
        select(AdvertisingStatDaily.campaign_id)
        .where(AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)))
        .distinct()
    )
    stmt = (
        select(AdvertisingWriteOffDaily.currency)
        .where(
            AdvertisingWriteOffDaily.stat_date >= date_from,
            AdvertisingWriteOffDaily.stat_date <= date_to,
            AdvertisingWriteOffDaily.currency != "",
            AdvertisingWriteOffDaily.payment_type.not_in(sorted(BONUS_PAYMENT_TYPES)),
            AdvertisingWriteOffDaily.campaign_id.in_(campaigns),
        )
        .group_by(AdvertisingWriteOffDaily.currency)
        .order_by(AdvertisingWriteOffDaily.currency)
    )
    return [str(currency) for currency in (await session.execute(stmt)).scalars()]
