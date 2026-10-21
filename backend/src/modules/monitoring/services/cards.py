"""Catalogue-card loaders exposed through the monitoring contract.

Split out of :mod:`.exports` on 2026-09-05: those loaders answer "what did this
SKU earn", these answer "which SKU is this", and the file was approaching the
repo's 500-line ceiling. The rules of :mod:`.exports` apply unchanged — module
level functions, caller owns the transaction, **every** query scoped by
``workspace_id`` through
:func:`~src.modules.monitoring.repos.base.workspace_sku_select`.

The A/B-tests article picker is the only consumer today. It needs the tenant in
the question rather than as a filter applied afterwards: WB article numbers are
global, so "does this article exist" and "does this article belong to the
caller" are different questions and only the second one is safe to act on.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    ProductCard,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.base import workspace_sku_select

#: How far back the picker's ranking looks. A week is what a seller means by
#: "sales over the last week", and it is short enough that a card which
#: stopped selling drops down the list within days rather than within a month.
RANKING_DAYS: int = 7


class WorkspaceCard(NamedTuple):
    """One catalogue card, as another module needs to identify a SKU.

    The A/B-tests module picks a card before it will let a test be created: a
    test names a WB article, and an article that is not in the workspace's
    catalogue cannot be rotated, cannot be advertised, and would send a media
    upload at somebody else's card — or at nothing.

    Attributes:
        nm_id: WB article.
        vendor_code: Seller article code («Артикул продавца»).
        title: Card title.
        orders_7d: Ordered units over the last :data:`RANKING_DAYS` days. Zero
            for a card the funnel history has not covered — the picker ranks
            with it, it does not report it as a measured zero.
        has_ads: Whether the card served advertising in the same window. It is
            the FIRST sort key rather than a tiebreak because an A/B rotation
            on «по показам» only advances while the card is being advertised:
            a card with no advertising is one the default trigger cannot move.
    """

    nm_id: int
    vendor_code: str
    title: str
    orders_7d: int = 0
    has_ads: bool = False


async def load_workspace_card(
    session: AsyncSession, *, workspace_id: uuid.UUID, nm_id: int
) -> WorkspaceCard | None:
    """Resolve one SKU inside a workspace's catalogue.

    The tenant is part of the question, not a filter applied afterwards: WB
    article numbers are global, so "does this article exist" and "does this
    article belong to the caller" are different questions and only the second
    one is safe to act on.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The workspace the card must belong to.
        nm_id: WB article to resolve.

    Returns:
        The card, or ``None`` when this workspace has no such SKU. The ranking
        fields are left at their defaults — this answers identity, not demand.
    """
    stmt = select(ProductCard.nm_id, ProductCard.vendor_code, ProductCard.title).where(
        ProductCard.workspace_id == workspace_id, ProductCard.nm_id == nm_id
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return WorkspaceCard(nm_id=int(row[0]), vendor_code=str(row[1] or ""), title=str(row[2] or ""))


async def search_workspace_cards(
    session: AsyncSession, *, workspace_id: uuid.UUID, needle: str, limit: int = 20
) -> list[WorkspaceCard]:
    """Find a workspace's cards by seller article, WB article or title.

    Widened from the vendor-code-only search because a picker that accepts one
    of the two identifiers still lets somebody type the other and get nothing,
    which reads as "this SKU does not exist". The WB article is matched as text
    so a pasted fragment works, the same way the A/B list's own search does.

    **Ordering is the answer to "which card would I actually test".** Alphabetical
    by vendor code put whatever the seller happened to code «A-001» at the top
    of a picker that opens before a single character is typed. The order is now
    advertised cards first, then last week's ordered units descending, and the
    vendor code only as a tiebreak between cards that are equally idle.

    The two aggregates are grouped subqueries over a seven-day window, joined to
    the page of cards; both source tables carry a ``(nm_id, stat_date)`` index,
    so this is a pair of small index range scans rather than a scan of the
    history.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        needle: Fragment of either article, or of the title.
        limit: Maximum cards to return.

    Returns:
        Matching cards, ranked as above and capped at ``limit``. An empty needle
        returns the first page of the catalogue rather than nothing, so the
        picker can open with something in it.
    """
    since = moscow_today() - timedelta(days=RANKING_DAYS)
    scope = workspace_sku_select(workspace_id)

    orders = (
        select(
            SalesFunnelDaily.nm_id.label("nm_id"),
            func.sum(SalesFunnelDaily.order_count).label("orders"),
        )
        .where(SalesFunnelDaily.nm_id.in_(scope), SalesFunnelDaily.stat_date >= since)
        .group_by(SalesFunnelDaily.nm_id)
        .subquery()
    )
    ads = (
        select(AdvertisingStatDaily.nm_id.label("nm_id"))
        .where(
            AdvertisingStatDaily.nm_id.in_(scope),
            AdvertisingStatDaily.stat_date >= since,
            AdvertisingStatDaily.views > 0,
        )
        .group_by(AdvertisingStatDaily.nm_id)
        .subquery()
    )

    ordered = func.coalesce(orders.c.orders, 0)
    advertised = ads.c.nm_id.is_not(None)

    stmt = (
        select(ProductCard.nm_id, ProductCard.vendor_code, ProductCard.title, ordered, advertised)
        .outerjoin(orders, orders.c.nm_id == ProductCard.nm_id)
        .outerjoin(ads, ads.c.nm_id == ProductCard.nm_id)
        .where(ProductCard.workspace_id == workspace_id)
    )
    fragment = needle.strip()
    if fragment:
        pattern = f"%{fragment}%"
        stmt = stmt.where(
            or_(
                ProductCard.vendor_code.ilike(pattern),
                ProductCard.title.ilike(pattern),
                cast(ProductCard.nm_id, String).like(f"%{fragment}%"),
            )
        )
    stmt = stmt.order_by(
        advertised.desc(), ordered.desc(), ProductCard.vendor_code, ProductCard.nm_id
    ).limit(limit)

    return [
        WorkspaceCard(
            nm_id=int(row[0]),
            vendor_code=str(row[1] or ""),
            title=str(row[2] or ""),
            orders_7d=int(row[3] or 0),
            has_ads=bool(row[4]),
        )
        for row in (await session.execute(stmt)).all()
    ]


__all__ = [
    "RANKING_DAYS",
    "WorkspaceCard",
    "load_workspace_card",
    "search_workspace_cards",
]
