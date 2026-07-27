"""Shared plumbing for the backfill phases.

The service graph and the phase counters both phases and orchestrator need,
kept here so no phase module has to import another.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import IntegrationError
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService

#: WB statuses whose campaigns can carry historical spend: completed (7),
#: active (9), paused (11). Declined/deleting campaigns never delivered.
_BACKFILL_STATUSES: frozenset[int] = frozenset({7, 9, 11})

#: fullstats hard cap on one request's window.
_FULLSTATS_WINDOW_DAYS = 31


@dataclass
class PhaseTotals:
    """Row counters accumulated across workspaces for the final report."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, value: int) -> None:
        """Accumulate ``value`` under ``key``."""
        self.counts[key] = self.counts.get(key, 0) + value

    def render(self) -> str:
        """Human-readable ``key=value`` summary line."""
        if not self.counts:
            return "nothing to do"
        return ", ".join(f"{key}={value}" for key, value in sorted(self.counts.items()))


def _build_service(session: AsyncSession) -> IngestionService:
    """Wire the full ingestion service graph onto one session."""
    return IngestionService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
        price_repo=PriceRepository(session),
        sale_repo=SaleRepository(session),
    )


def _is_http_400(exc: IntegrationError) -> bool:
    """Whether a client error signals "window not served" (retention floor)."""
    return "error 400" in str(exc)
