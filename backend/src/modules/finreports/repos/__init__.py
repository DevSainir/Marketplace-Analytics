"""Data-access layer for the ``finreports`` module.

Repositories own all SQL; services never touch a session directly (Clean
Architecture). Each is bound to the request-scoped ``AsyncSession`` and shares
the idempotent :class:`BaseRepository.bulk_upsert` (re-harvest overwrites).
"""

from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.cost_price import CostPriceRepository
from src.modules.finreports.repos.financial_report import FinancialReportRepository
from src.modules.finreports.repos.pnl import (
    PnlGrouping,
    PnlRepository,
    ReasonAmount,
    SettlementAggregate,
    SkuUnits,
)
from src.modules.finreports.repos.transaction import (
    LogisticsTransactionRepository,
    SkuLogisticsAggregate,
    SkuRepricingPlan,
)

__all__ = [
    "BaseRepository",
    "CostPriceRepository",
    "FinancialReportRepository",
    "LogisticsTransactionRepository",
    "PnlGrouping",
    "PnlRepository",
    "ReasonAmount",
    "SettlementAggregate",
    "SkuLogisticsAggregate",
    "SkuRepricingPlan",
    "SkuUnits",
]
