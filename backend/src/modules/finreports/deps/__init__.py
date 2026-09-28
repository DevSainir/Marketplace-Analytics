"""Dependency-injection wiring for the ``finreports`` module.

Assembles the repository -> service graph from the global ``DbSession``. The
session or repository (router -> service -> repo -> model).
"""

from __future__ import annotations

import pathlib
import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.core.config import settings
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
    SkuExclusionRepository,
)
from src.modules.finreports.services import (
    BalanceService,
    CostPriceService,
    HarvestControlService,
    IngestionService,
    PnlService,
    SkuReportService,
)
)
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
PnlRepoDep = Annotated[PnlRepository, Depends(get_pnl_repo)]
CostRepoDep = Annotated[CostPriceRepository, Depends(get_cost_repo)]
ExclusionRepoDep = Annotated[SkuExclusionRepository, Depends(get_exclusion_repo)]
BalancePinRepoDep = Annotated[BalancePinRepository, Depends(get_balance_pin_repo)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #

    Deliberately NOT ``lru_cache``d, unlike its stateless neighbours: it holds a
    Redis client, and ``get_redis()`` hands each event loop its own — a cached
    holder would pin whichever loop built it first
    (``tests/unit/core/test_no_loop_bound_state_outlives_a_task.py``). Building
    it costs one small object. A TTL of 0 turns caching off entirely, degrading
    to a recompute on every call.
    """
    if settings.finreports_summary_cache_ttl_seconds <= 0:
        get_redis(), ttl_seconds=settings.finreports_summary_cache_ttl_seconds
    )


    transaction_repo: TransactionRepoDep,
    billed_repo: BilledRepoDep,
    report_repo: ReportRepoDep,
    penalty_repo: PenaltyRepoDep,
    measurement_repo: MeasurementRepoDep,
        transaction_repo=transaction_repo,
        billed_repo=billed_repo,
        report_repo=report_repo,
        penalty_repo=penalty_repo,
        measurement_repo=measurement_repo,
        summary_cache=_summary_cache(),
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
    billed_repo: BilledRepoDep,
    report_repo: ReportRepoDep,
    penalty_repo: PenaltyRepoDep,
    measurement_repo: MeasurementRepoDep,
        package_cache=_package_cache(),
            transaction_repo=transaction_repo,
            billed_repo=billed_repo,
            report_repo=report_repo,
            penalty_repo=penalty_repo,
            measurement_repo=measurement_repo,
        ),
    )


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
    )


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
PnlServiceDep = Annotated[PnlService, Depends(get_pnl_service)]
SkuReportServiceDep = Annotated[SkuReportService, Depends(get_sku_report_service)]
CostPriceServiceDep = Annotated[CostPriceService, Depends(get_cost_price_service)]
BalanceServiceDep = Annotated[BalanceService, Depends(get_balance_service)]
HarvestControlServiceDep = Annotated[HarvestControlService, Depends(get_harvest_control_service)]

__all__ = [
    "BalancePinRepoDep",
    "BalanceServiceDep",
    "BaselineRepoDep",
    "BilledRepoDep",
    "CostPriceServiceDep",
    "CostRepoDep",
    "ExclusionRepoDep",
    "IngestionServiceDep",
    "PenaltyRepoDep",
    "PnlRepoDep",
    "PnlServiceDep",
    "ReportRepoDep",
    "SkuReportServiceDep",
    "TransactionRepoDep",
]
