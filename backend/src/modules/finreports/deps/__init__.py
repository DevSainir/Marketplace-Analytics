"""Dependency-injection wiring for the ``finreports`` module.

Assembles the repository -> service graph from the global ``DbSession``. The
session or repository (router -> service -> repo -> model).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
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
        transaction_repo=transaction_repo,
        baseline_repo=baseline_repo,
        billed_repo=billed_repo,
        report_repo=report_repo,
        penalty_repo=penalty_repo,
    )


def get_ingestion_service(
    transaction_repo: TransactionRepoDep,
    report_repo: ReportRepoDep,
    baseline_repo: BaselineRepoDep,
    billed_repo: BilledRepoDep,
    penalty_repo: PenaltyRepoDep,
) -> IngestionService:
    """Compose the write-side :class:`IngestionService` from its repositories."""
    return IngestionService(
        transaction_repo=transaction_repo,
        report_repo=report_repo,
        baseline_repo=baseline_repo,
        billed_repo=billed_repo,
        penalty_repo=penalty_repo,
    )


    transaction_repo: TransactionRepoDep,
    baseline_repo: BaselineRepoDep,
    billed_repo: BilledRepoDep,
    report_repo: ReportRepoDep,
    penalty_repo: PenaltyRepoDep,
            transaction_repo=transaction_repo,
            baseline_repo=baseline_repo,
            billed_repo=billed_repo,
            report_repo=report_repo,
            penalty_repo=penalty_repo,
        )
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
