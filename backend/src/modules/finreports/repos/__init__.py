"""Data-access layer for the ``finreports`` module.

Repositories own all SQL; services never touch a session directly (Clean
Architecture). Each is bound to the request-scoped ``AsyncSession`` and shares
the idempotent :class:`BaseRepository.bulk_upsert` (re-harvest overwrites).
"""

from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.financial_report import FinancialReportRepository
from src.modules.finreports.repos.transaction import (
    LogisticsTransactionRepository,
    SkuLogisticsAggregate,
)

__all__ = [
    "BaseRepository",
    "FinancialReportRepository",
    "LogisticsTransactionRepository",
    "SkuLogisticsAggregate",
]
