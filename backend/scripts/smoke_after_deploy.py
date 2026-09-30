"""Open «Демо»'s busiest SKU cards on the code that was just deployed.

The deploy's own health checks prove the containers are up and nginx answers
200 — and on 2026-09-29 both were true for three hours while every SKU card
answered 500. `/health` touches no tenant data, and the failure lived in how a
real row from before a migration was turned into a response. The only probe that
sees that class of bug is one that reads real rows through the real service.

So this does, and only for the one кабинет a diagnostic may read: the session is
`diagnostic_session()` — read-only at the transaction level and pinned to
«Демо» by row-level security — so the cards picked below are that кабинет's
and nobody else's. It prints counts and status, never figures.

Run by the deploy inside the freshly rotated api container. Any non-zero exit
fails the deploy before worker and beat are updated; it does NOT roll back —
that is a human's call (scripts/deploy/rollback.sh). Exit 3 means it could not
check at all — no cards to open — and still fails, because a guard that skips
itself must not look like a pass.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.diagnostics import diagnostic_session, diagnostic_workspace
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

#: The whole probe must finish well inside the deploy job's own timeout.
TIMEOUT_SECONDS = 120

EXIT_BROKEN = 1
EXIT_CANNOT_CHECK = 3


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


async def smoke(session: AsyncSession, *, workspace_id: uuid.UUID) -> tuple[list[int], list[str]]:
    """Render the monitoring list and the busiest cards; collect what failed.

    Returns:
        ``(cards_opened, failures)`` — a failure is ``"<what>: <exception>"``.
    """
    service = _service(session)
    failures: list[str] = []
    try:
        (await service.get_summary(workspace_id=workspace_id, limit=20)).model_dump_json()
    except Exception as exc:  # every failure is the finding
        failures.append(f"summary: {type(exc).__name__}: {exc}")
    cards = await busiest_cards(session)
    for nm_id in cards:
        try:
            (await service.get_detail(nm_id=nm_id)).model_dump_json()
        except Exception as exc:  # every failure is the finding
            failures.append(f"card {nm_id}: {type(exc).__name__}: {exc}")
    return cards, failures


async def _run() -> int:
    async with diagnostic_session() as session:
        cards, failures = await smoke(session, workspace_id=diagnostic_workspace())
    if failures:
        for failure in failures:
            print(f"smoke: FAILED {failure}", file=sys.stderr)
        return EXIT_BROKEN
    if not cards:
        print("smoke: no cards with recent orders to open; nothing was checked", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    print(f"smoke: ok — monitoring list and {len(cards)} cards rendered")
    return 0


def main() -> int:
    """Run the probe under a hard ceiling; a hang is a failure, not a pass."""
    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=TIMEOUT_SECONDS))
    except TimeoutError:
        print(f"smoke: FAILED no answer in {TIMEOUT_SECONDS}s", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
