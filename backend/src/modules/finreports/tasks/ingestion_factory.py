"""One wiring of the ingestion service, shared by everything that writes.

Its own module because three callers need it and none of them owns it: the
takes it as an *argument* rather than importing it, so that
:mod:`~src.modules.finreports.tasks.settlement` never reaches back into the
harvest that calls it. Keeping the factory here is what lets that injection stay
honest instead of being a circular import with extra steps.
"""

from __future__ import annotations

from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
    SettlementUploadRepository,
)
from src.modules.finreports.services import IngestionService


def build_ingestion(session: object) -> IngestionService:
    """Wire an :class:`IngestionService` on a fresh session."""
    return IngestionService(
        transaction_repo=LogisticsTransactionRepository(session),  # type: ignore[arg-type]
        report_repo=FinancialReportRepository(session),  # type: ignore[arg-type]
        upload_repo=SettlementUploadRepository(session),  # type: ignore[arg-type]
    )


__all__ = ["build_ingestion"]
