"""Dependency-injection wiring for the ``finreports`` module.

Assembles the repository -> service graph from the global ``DbSession``. The
session or repository (router -> service -> repo -> model).
"""

from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.core.config import settings
from src.core.deps import DbSession
from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    LogisticsTransactionRepository,
    PnlRepository,
)
from src.modules.finreports.services import (
    CostPriceService,
    IngestionService,
    PnlService,
    SkuReportService,
)
)


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #
def get_transaction_repo(session: DbSession) -> LogisticsTransactionRepository:
    """Provide a :class:`LogisticsTransactionRepository` for the request."""
    return LogisticsTransactionRepository(session)








def get_report_repo(session: DbSession) -> FinancialReportRepository:
    """Provide a :class:`FinancialReportRepository` for the request."""
    return FinancialReportRepository(session)






def get_pnl_repo(session: DbSession) -> PnlRepository:
    """Provide a :class:`PnlRepository` for the request."""
    return PnlRepository(session)


def get_cost_repo(session: DbSession) -> CostPriceRepository:
    """Provide a :class:`CostPriceRepository` for the request."""
    return CostPriceRepository(session)


TransactionRepoDep = Annotated[LogisticsTransactionRepository, Depends(get_transaction_repo)]
ReportRepoDep = Annotated[FinancialReportRepository, Depends(get_report_repo)]
PnlRepoDep = Annotated[PnlRepository, Depends(get_pnl_repo)]
CostRepoDep = Annotated[CostPriceRepository, Depends(get_cost_repo)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
    transaction_repo: TransactionRepoDep,
    baseline_repo: BaselineRepoDep,
    billed_repo: BilledRepoDep,
    report_repo: ReportRepoDep,
    penalty_repo: PenaltyRepoDep,
    measurement_repo: MeasurementRepoDep,
        transaction_repo=transaction_repo,
        baseline_repo=baseline_repo,
        billed_repo=billed_repo,
        report_repo=report_repo,
        penalty_repo=penalty_repo,
        measurement_repo=measurement_repo,
    )


def get_pnl_service(
    pnl_repo: PnlRepoDep,
    cost_repo: CostRepoDep,
    report_repo: ReportRepoDep,
) -> PnlService:
    """Compose the read-side :class:`PnlService` from its repositories."""
    return PnlService(pnl_repo=pnl_repo, cost_repo=cost_repo, report_repo=report_repo)


def get_cost_price_service(cost_repo: CostRepoDep, pnl_repo: PnlRepoDep) -> CostPriceService:
    """Compose the :class:`CostPriceService` (needs settled units for coverage)."""
    return CostPriceService(cost_repo=cost_repo, pnl_repo=pnl_repo)


def get_sku_report_service(pnl_repo: PnlRepoDep, cost_repo: CostRepoDep) -> SkuReportService:
    """Compose the :class:`SkuReportService` for the per-SKU P&L report."""
    return SkuReportService(pnl_repo=pnl_repo, cost_repo=cost_repo)


def get_ingestion_service(
    transaction_repo: TransactionRepoDep,
    report_repo: ReportRepoDep,
    baseline_repo: BaselineRepoDep,
    billed_repo: BilledRepoDep,
    penalty_repo: PenaltyRepoDep,
    measurement_repo: MeasurementRepoDep,
) -> IngestionService:
    """Compose the write-side :class:`IngestionService` from its repositories."""
    return IngestionService(
        transaction_repo=transaction_repo,
        report_repo=report_repo,
        baseline_repo=baseline_repo,
        billed_repo=billed_repo,
        penalty_repo=penalty_repo,
        measurement_repo=measurement_repo,
    )


@lru_cache(maxsize=1)

    Cached with ``lru_cache`` because the store is stateless configuration, not
    per-request state — a new object per request would be pure waste. An empty
    ``finreports_package_cache_dir`` turns caching off entirely.
    """
    configured = settings.finreports_package_cache_dir.strip()
    if not configured:
        pathlib.Path(configured), max_entries=settings.finreports_package_cache_entries
    )


    transaction_repo: TransactionRepoDep,
    baseline_repo: BaselineRepoDep,
    billed_repo: BilledRepoDep,
    report_repo: ReportRepoDep,
    penalty_repo: PenaltyRepoDep,
    measurement_repo: MeasurementRepoDep,
        package_cache=_package_cache(),
            transaction_repo=transaction_repo,
            baseline_repo=baseline_repo,
            billed_repo=billed_repo,
            report_repo=report_repo,
            penalty_repo=penalty_repo,
            measurement_repo=measurement_repo,
        ),
    )


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
PnlServiceDep = Annotated[PnlService, Depends(get_pnl_service)]
SkuReportServiceDep = Annotated[SkuReportService, Depends(get_sku_report_service)]
CostPriceServiceDep = Annotated[CostPriceService, Depends(get_cost_price_service)]

__all__ = [
    "BaselineRepoDep",
    "BilledRepoDep",
    "CostPriceServiceDep",
    "CostRepoDep",
    "IngestionServiceDep",
    "PenaltyRepoDep",
    "PnlRepoDep",
    "PnlServiceDep",
    "ReportRepoDep",
    "SkuReportServiceDep",
    "TransactionRepoDep",
]
