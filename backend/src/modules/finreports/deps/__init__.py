"""Dependency-injection wiring for the ``finreports`` module.

Assembles the repository -> service graph from the global ``DbSession``. The
presentation layer depends only on the ``*ServiceDep`` aliases; it never sees a
session or repository (router -> service -> repo -> model).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
from src.core.redis import get_redis
from src.modules.finreports.constants import FRESHNESS_RECORD_TTL_SECONDS
from src.modules.finreports.repos import (
    BalancePinRepository,
    CostPriceRepository,
    DailySettlementRepository,
    FinancialReportRepository,
    LogisticsTransactionRepository,
    PnlRepository,
    SettlementUploadRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.services import (
    BalanceService,
    CostPriceService,
    HarvestControlService,
    IngestionService,
    PeriodService,
    PnlService,
    SettlementUploadService,
    SkuReportService,
)
from src.modules.finreports.services.freshness_record import RedisFreshnessRecordStore
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
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


def get_daily_repo(session: DbSession) -> DailySettlementRepository:
    """Provide a :class:`DailySettlementRepository` for the request."""
    return DailySettlementRepository(session)


def get_pnl_repo(session: DbSession) -> PnlRepository:
    """Provide a :class:`PnlRepository` for the request."""
    return PnlRepository(session)


def get_cost_repo(session: DbSession) -> CostPriceRepository:
    """Provide a :class:`CostPriceRepository` for the request."""
    return CostPriceRepository(session)


def get_exclusion_repo(session: DbSession) -> SkuExclusionRepository:
    """Provide a :class:`SkuExclusionRepository` for the request."""
    return SkuExclusionRepository(session)


def get_balance_pin_repo(session: DbSession) -> BalancePinRepository:
    """Provide a :class:`BalancePinRepository` for the request."""
    return BalancePinRepository(session)


TransactionRepoDep = Annotated[LogisticsTransactionRepository, Depends(get_transaction_repo)]
ReportRepoDep = Annotated[FinancialReportRepository, Depends(get_report_repo)]
DailyRepoDep = Annotated[DailySettlementRepository, Depends(get_daily_repo)]
PnlRepoDep = Annotated[PnlRepository, Depends(get_pnl_repo)]
CostRepoDep = Annotated[CostPriceRepository, Depends(get_cost_repo)]
ExclusionRepoDep = Annotated[SkuExclusionRepository, Depends(get_exclusion_repo)]
BalancePinRepoDep = Annotated[BalancePinRepository, Depends(get_balance_pin_repo)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
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


def get_balance_service(
    pnl_repo: PnlRepoDep, cost_repo: CostRepoDep, pin_repo: BalancePinRepoDep
) -> BalanceService:
    """Compose the :class:`BalanceService` for the stock-balance grid."""
    return BalanceService(pnl_repo=pnl_repo, cost_repo=cost_repo, pin_repo=pin_repo)


def get_sku_report_service(
    pnl_repo: PnlRepoDep, cost_repo: CostRepoDep, exclusion_repo: ExclusionRepoDep
) -> SkuReportService:
    """Compose the :class:`SkuReportService` for the per-SKU P&L report."""
    return SkuReportService(pnl_repo=pnl_repo, cost_repo=cost_repo, exclusion_repo=exclusion_repo)


def get_ingestion_service(
    transaction_repo: TransactionRepoDep,
    report_repo: ReportRepoDep,
) -> IngestionService:
    """Compose the write-side :class:`IngestionService` from its repositories."""
    return IngestionService(transaction_repo=transaction_repo, report_repo=report_repo)


def get_harvest_control_service(
    session: DbSession, report_repo: ReportRepoDep
) -> HarvestControlService:
    """Compose the :class:`HarvestControlService` behind «Обновить».

    Takes the shared Redis directly for the lock — it reads one key and holds no
    state worth caching — and a Redis-backed freshness record store for the P&L's
    freshness line. Both fail open: an unreachable Redis costs the page its
    footnote and the button its «уже выполняется», never the statement.
    """

    async def _load_tokens(workspace_id: uuid.UUID) -> WorkspaceTokenBundle | None:
        """Resolve one workspace's WB credentials on the request's own session.

        Scoped deliberately: «Обновить» needs the caller's statistics token to
        name their rate bucket, and decrypting every tenant's secrets to answer
        one tenant's click would be a poor trade.
        """
        return await load_workspace_token_bundle(session, workspace_id)

    return HarvestControlService(
        report_repo=report_repo,
        daily_repo=DailySettlementRepository(session),
        redis=get_redis(),
        freshness_records=RedisFreshnessRecordStore(
            get_redis(), ttl_seconds=FRESHNESS_RECORD_TTL_SECONDS
        ),
        load_tokens=_load_tokens,
        upload_repo=SettlementUploadRepository(session),
    )


def get_period_service(session: DbSession, report_repo: ReportRepoDep) -> PeriodService:
    """Compose the :class:`PeriodService` behind the period picker (``/weeks``)."""
    return PeriodService(
        report_repo=report_repo,
        daily_repo=DailySettlementRepository(session),
        upload_repo=SettlementUploadRepository(session),
    )


def get_settlement_upload_service(session: DbSession) -> SettlementUploadService:
    """Compose the :class:`SettlementUploadService` behind «Загрузить отчёт»."""
    return SettlementUploadService(upload_repo=SettlementUploadRepository(session))


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
PnlServiceDep = Annotated[PnlService, Depends(get_pnl_service)]
SkuReportServiceDep = Annotated[SkuReportService, Depends(get_sku_report_service)]
CostPriceServiceDep = Annotated[CostPriceService, Depends(get_cost_price_service)]
BalanceServiceDep = Annotated[BalanceService, Depends(get_balance_service)]
PeriodServiceDep = Annotated[PeriodService, Depends(get_period_service)]
HarvestControlServiceDep = Annotated[HarvestControlService, Depends(get_harvest_control_service)]
SettlementUploadServiceDep = Annotated[
    SettlementUploadService, Depends(get_settlement_upload_service)
]

__all__ = [
    "BalancePinRepoDep",
    "BalanceServiceDep",
    "CostPriceServiceDep",
    "CostRepoDep",
    "ExclusionRepoDep",
    "IngestionServiceDep",
    "PeriodServiceDep",
    "PnlRepoDep",
    "PnlServiceDep",
    "ReportRepoDep",
    "SkuReportServiceDep",
    "TransactionRepoDep",
]
