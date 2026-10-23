"""Heatmap: the grid and the catalogue behind its filters.

What ``HeatmapView`` asks for when it opens (``frontend/src/modules/heatmap/store.js``,
``init``): ``GET /heatmap`` and ``GET /heatmap/catalog``, both over the thirty
days ending yesterday — the route's own default window — with the grid painted
by orders, a column per day and a row per article, nothing filtered. The service
is built by ``heatmap/deps``, from the two finreports services that module's
deps hand it, as a request builds it.

The route warns that this GET can write: a finance metric reads the settlement
rollup, which rebuilds stale days. The default metric reads only the funnel, so
the grid the page opens on never reaches the rollup, and that is the one opened.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke.report import SmokeReport, attempt
from src.core.timeutils import moscow_today
from src.modules.finreports.deps import get_pnl_service, get_sku_report_service
from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.heatmap.deps import get_group_repo, get_heatmap_service
from src.modules.heatmap.routers.heatmap import DEFAULT_WINDOW_DAYS
from src.modules.heatmap.services import HeatmapQuery


async def check_heatmap(
    session: AsyncSession, report: SmokeReport, *, workspace_id: uuid.UUID
) -> None:
    """Open the heatmap page the way the SPA does on a first visit."""
    pnl_repo, cost_repo = PnlRepository(session), CostPriceRepository(session)
    service = get_heatmap_service(
        groups=get_group_repo(session),
        pnl=get_pnl_service(pnl_repo, cost_repo, FinancialReportRepository(session)),
        skus=get_sku_report_service(pnl_repo, cost_repo, SkuExclusionRepository(session)),
    )
    end = moscow_today() - timedelta(days=1)
    start = end - timedelta(days=DEFAULT_WINDOW_DAYS - 1)

    async def grid() -> int:
        query = HeatmapQuery(
            date_from=start,
            date_to=end,
            period="day",
            group_by="sku",
            metric="orders",
            metric2=None,
        )
        answer = await service.build(session, workspace_id=workspace_id, query=query)
        answer.model_dump_json()
        return len(answer.rows)

    async def catalogue() -> int:
        answer = await service.catalog(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        )
        answer.model_dump_json()
        return len(answer.items)

    await attempt(session, report, "heatmap", grid)
    await attempt(session, report, "heatmap catalogue", catalogue)


__all__ = ["check_heatmap"]
