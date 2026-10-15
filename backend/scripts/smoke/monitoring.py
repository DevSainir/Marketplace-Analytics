"""«Мониторинг»: the SKU list and the busiest SKU cards.

The page the probe was written for — on 2026-09-29 every card answered 500 on
rows from before a migration while the list itself rendered.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke.report import SmokeReport, attempt
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import ProductCard, SalesFunnelDaily
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    AdvertisingWriteOffRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    PinnedSkuRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    SkuDayActionRepository,
    SkuDayCommentRepository,
    StockRepository,
)
from src.modules.monitoring.services import AnalyticsService

#: Cards opened per deploy. The busiest ones, because a card with history is the
#: one that carries rows from before whatever the last migration changed.
CARDS = 3

#: The list's first page, as the SPA asks for it.
LIST_LIMIT = 20


def _service(session: AsyncSession) -> AnalyticsService:
    """The read service exactly as a request gets it (monitoring/deps)."""
    return AnalyticsService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
        advertising_write_off_repo=AdvertisingWriteOffRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        matrix_override_repo=MatrixOverrideRepository(session),
        price_repo=PriceRepository(session),
        sale_repo=SaleRepository(session),
        pinned_sku_repo=PinnedSkuRepository(session),
        day_comment_repo=SkuDayCommentRepository(session),
        day_action_repo=SkuDayActionRepository(session),
    )


async def busiest_cards(session: AsyncSession, *, limit: int = CARDS) -> list[int]:
    """The cards with the most orders in the last 30 days, busiest first.

    Through ``product_card``, which row-level security covers — the funnel table
    carries no workspace, so selecting from it alone would reach every кабинет.
    """
    since = moscow_today() - timedelta(days=30)
    rows = await session.execute(
        select(ProductCard.nm_id)
        .join(SalesFunnelDaily, SalesFunnelDaily.nm_id == ProductCard.nm_id)
        .where(SalesFunnelDaily.stat_date >= since)
        .group_by(ProductCard.nm_id)
        .order_by(func.sum(SalesFunnelDaily.order_count).desc(), ProductCard.nm_id)
        .limit(limit)
    )
    return list(rows.scalars())


async def check_monitoring(
    session: AsyncSession, report: SmokeReport, *, workspace_id: uuid.UUID
) -> None:
    """Render the monitoring list, then open the busiest cards one by one."""
    service = _service(session)

    async def summary() -> int:
        listing = await service.get_summary(workspace_id=workspace_id, limit=LIST_LIMIT)
        listing.model_dump_json()
        return len(listing.items)

    await attempt(session, report, "monitoring list", summary)
    report.cards = await busiest_cards(session)
    for nm_id in report.cards:

        async def card(nm_id: int = nm_id) -> int:
            (await service.get_detail(nm_id=nm_id)).model_dump_json()
            return 1

        await attempt(session, report, f"card {nm_id}", card, tally="cards")


__all__ = ["CARDS", "busiest_cards", "check_monitoring"]
