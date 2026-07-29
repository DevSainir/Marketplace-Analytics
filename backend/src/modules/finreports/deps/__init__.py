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
    FinancialReportRepository,
    LogisticsTransactionRepository,
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






TransactionRepoDep = Annotated[LogisticsTransactionRepository, Depends(get_transaction_repo)]
ReportRepoDep = Annotated[FinancialReportRepository, Depends(get_report_repo)]


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

__all__ = [
    "BaselineRepoDep",
    "BilledRepoDep",
    "IngestionServiceDep",
    "PenaltyRepoDep",
    "ReportRepoDep",
    "TransactionRepoDep",
]
