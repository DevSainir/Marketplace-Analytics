"""Data-access layer for the ``finreports`` module.

Repositories own all SQL; services never touch a session directly (Clean
Architecture). Each is bound to the request-scoped ``AsyncSession`` and shares
the idempotent :class:`BaseRepository.bulk_upsert` (re-harvest overwrites).
"""

from src.modules.finreports.repos.balance_pin import BalancePinRepository
from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.cost_price import CostPriceRepository
from src.modules.finreports.repos.financial_report import (
    FinancialReportRepository,
    LatestReportHeader,
)
from src.modules.finreports.repos.pnl import (
    PnlGrouping,
    PnlRepository,
    ReasonAmount,
    SettlementAggregate,
    SkuUnits,
)
from src.modules.finreports.repos.settlement_watermark import SettlementWatermarkRepository
from src.modules.finreports.repos.sku_exclusion import SkuExclusionRepository
from src.modules.finreports.repos.transaction import (
    LogisticsTransactionRepository,
    SkuLogisticsAggregate,
    SkuRepricingPlan,
)

__all__ = [
    "BalancePinRepository",
    "BaseRepository",
    "CostPriceRepository",
    "FinancialReportRepository",
    "LatestReportHeader",
    "LogisticsTransactionRepository",
    "PnlGrouping",
    "PnlRepository",
    "ReasonAmount",
    "SettlementAggregate",
    "SettlementWatermarkRepository",
    "SkuExclusionRepository",
    "SkuLogisticsAggregate",
    "SkuRepricingPlan",
    "SkuUnits",
]
