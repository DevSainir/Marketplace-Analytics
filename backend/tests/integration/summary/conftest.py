"""Fixtures for the «Сводка» integration tests.

The miniature WB week lives in the finreports package because that is the module
whose arithmetic it was written to prove. It is re-exported rather than copied:
«Сводка» is derived from that same report, and a second fifteen-row financial
fixture is how the two halves would start disagreeing about what the week
contained.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.services import PnlService
from src.modules.finreports.services.pnl import SkuReportService
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    PriceSnapshot,
    ProductCard,
    SalesFunnelDaily,
)
from src.modules.summary.services import SummaryService
from tests.integration.finreports.conftest import (
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
    seeded,
)


def _service(session: AsyncSession) -> SummaryService:
    """Wire the summary on the test session, through the real finreports services."""
    pnl_repo = PnlRepository(session)
    cost_repo = CostPriceRepository(session)
    return SummaryService(
        pnl=PnlService(
            pnl_repo=pnl_repo,
            cost_repo=cost_repo,
            report_repo=FinancialReportRepository(session),
        ),
        skus=SkuReportService(
            pnl_repo=pnl_repo,
            cost_repo=cost_repo,
            exclusion_repo=SkuExclusionRepository(session),
        ),
    )


@pytest.fixture
async def catalogued(db_session: AsyncSession, seeded: None) -> None:
    """The week's SKUs, plus one funnel and one advertising day each.

    Both monitoring tables are keyed by ``nm_id`` alone, so a card row is what
    ties them to a workspace at all — which is exactly the join under test.
    """
    db_session.add_all(
        [
            ProductCard(nm_id=SKU_A, workspace_id=WORKSPACE, vendor_code="sku-a"),
            ProductCard(nm_id=SKU_B, workspace_id=WORKSPACE, vendor_code="sku-b"),
            SalesFunnelDaily(stat_date=WINDOW_FROM, nm_id=SKU_A, order_count=40, buyout_count=12),
            SalesFunnelDaily(stat_date=WINDOW_TO, nm_id=SKU_B, order_count=60, buyout_count=18),
            # A price for the FIRST day only: the ДРР line needs the ordered
            # money, WB's funnel publishes none, and the day we never
            # snapshotted a price for has to stay unknown rather than free.
            PriceSnapshot(stat_date=WINDOW_FROM, nm_id=SKU_A, seller_price=Decimal("2500")),
            AdvertisingStatDaily(
                stat_date=WINDOW_FROM,
                campaign_id=1,
                app_type=1,
                nm_id=SKU_A,
                spend=Decimal("150"),
            ),
        ]
    )
    await db_session.flush()


__all__ = ["catalogued", "seeded"]
