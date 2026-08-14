"""Dependency-injection wiring for the Monitoring module.

Assembles the repository -> service graph from the global ``DbSession``. The
presentation layer depends only on :data:`AnalyticsServiceDep`; it never sees a
session or repository, preserving the router -> service -> repo -> model flow.

A package rather than a flat ``deps.py`` only because this module's wiring
outgrew one file; the exported ``Annotated`` aliases are the same either way
(see the ``backend-architecture`` skill, "Dependency injection").
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.config import settings
from src.core.deps import DbSession
from src.core.exceptions import NotFoundError
from src.integrations.wildberries import build_search_client
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    PinnedSkuRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    SkuDayActionRepository,
    SkuDayCommentRepository,
    StockRepository,
    WarehouseMarkRepository,
)
from src.modules.monitoring.services import AnalyticsService, ClusterAnalytics
from src.modules.workspaces.contract import CurrentWorkspaceId


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #
def get_funnel_repo(session: DbSession) -> FunnelRepository:
    """Provide a :class:`FunnelRepository` bound to the request session."""
    return FunnelRepository(session)


def get_advertising_repo(session: DbSession) -> AdvertisingRepository:
    """Provide an :class:`AdvertisingRepository` bound to the request session."""
    return AdvertisingRepository(session)


def get_advertising_search_repo(session: DbSession) -> AdvertisingSearchRepository:
    """Provide an :class:`AdvertisingSearchRepository` bound to the request session."""
    return AdvertisingSearchRepository(session)


def get_advertising_cluster_repo(session: DbSession) -> AdvertisingClusterRepository:
    """Provide an :class:`AdvertisingClusterRepository` bound to the request session."""
    return AdvertisingClusterRepository(session)


def get_stock_repo(session: DbSession) -> StockRepository:
    """Provide a :class:`StockRepository` bound to the request session."""
    return StockRepository(session)


def get_campaign_repo(session: DbSession) -> CampaignRepository:
    """Provide a :class:`CampaignRepository` bound to the request session."""
    return CampaignRepository(session)


def get_product_card_repo(session: DbSession) -> ProductCardRepository:
    """Provide a :class:`ProductCardRepository` bound to the request session."""
    return ProductCardRepository(session)


def get_product_size_repo(session: DbSession) -> ProductSizeRepository:
    """Provide a :class:`ProductSizeRepository` bound to the request session."""
    return ProductSizeRepository(session)


def get_matrix_override_repo(session: DbSession) -> MatrixOverrideRepository:
    """Provide a :class:`MatrixOverrideRepository` bound to the request session."""
    return MatrixOverrideRepository(session)


def get_price_repo(session: DbSession) -> PriceRepository:
    """Provide a :class:`PriceRepository` bound to the request session."""
    return PriceRepository(session)


def get_sale_repo(session: DbSession) -> SaleRepository:
    """Provide a :class:`SaleRepository` bound to the request session."""
    return SaleRepository(session)


def get_warehouse_mark_repo(session: DbSession) -> WarehouseMarkRepository:
    """Provide a :class:`WarehouseMarkRepository` bound to the request session."""
    return WarehouseMarkRepository(session)


def get_pinned_sku_repo(session: DbSession) -> PinnedSkuRepository:
    """Provide a :class:`PinnedSkuRepository` bound to the request session."""
    return PinnedSkuRepository(session)


def get_day_comment_repo(session: DbSession) -> SkuDayCommentRepository:
    """Provide a :class:`SkuDayCommentRepository` bound to the request session."""
    return SkuDayCommentRepository(session)


def get_day_action_repo(session: DbSession) -> SkuDayActionRepository:
    """Provide a :class:`SkuDayActionRepository` bound to the request session."""
    return SkuDayActionRepository(session)


FunnelRepoDep = Annotated[FunnelRepository, Depends(get_funnel_repo)]
AdvertisingRepoDep = Annotated[AdvertisingRepository, Depends(get_advertising_repo)]
AdvertisingSearchRepoDep = Annotated[
    AdvertisingSearchRepository, Depends(get_advertising_search_repo)
]
AdvertisingClusterRepoDep = Annotated[
    AdvertisingClusterRepository, Depends(get_advertising_cluster_repo)
]
StockRepoDep = Annotated[StockRepository, Depends(get_stock_repo)]
CampaignRepoDep = Annotated[CampaignRepository, Depends(get_campaign_repo)]
ProductCardRepoDep = Annotated[ProductCardRepository, Depends(get_product_card_repo)]
ProductSizeRepoDep = Annotated[ProductSizeRepository, Depends(get_product_size_repo)]
MatrixOverrideRepoDep = Annotated[MatrixOverrideRepository, Depends(get_matrix_override_repo)]
PriceRepoDep = Annotated[PriceRepository, Depends(get_price_repo)]
SaleRepoDep = Annotated[SaleRepository, Depends(get_sale_repo)]
WarehouseMarkRepoDep = Annotated[WarehouseMarkRepository, Depends(get_warehouse_mark_repo)]
PinnedSkuRepoDep = Annotated[PinnedSkuRepository, Depends(get_pinned_sku_repo)]
SkuDayCommentRepoDep = Annotated[SkuDayCommentRepository, Depends(get_day_comment_repo)]
SkuDayActionRepoDep = Annotated[SkuDayActionRepository, Depends(get_day_action_repo)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def get_analytics_service(
    funnel_repo: FunnelRepoDep,
    advertising_repo: AdvertisingRepoDep,
    advertising_search_repo: AdvertisingSearchRepoDep,
    stock_repo: StockRepoDep,
    campaign_repo: CampaignRepoDep,
    product_card_repo: ProductCardRepoDep,
    product_size_repo: ProductSizeRepoDep,
    matrix_override_repo: MatrixOverrideRepoDep,
    price_repo: PriceRepoDep,
    sale_repo: SaleRepoDep,
    warehouse_mark_repo: WarehouseMarkRepoDep,
    pinned_sku_repo: PinnedSkuRepoDep,
    day_comment_repo: SkuDayCommentRepoDep,
    day_action_repo: SkuDayActionRepoDep,
) -> AnalyticsService:
    """Compose the read-side :class:`AnalyticsService` from its repositories."""
    return AnalyticsService(
        funnel_repo=funnel_repo,
        advertising_repo=advertising_repo,
        advertising_search_repo=advertising_search_repo,
        stock_repo=stock_repo,
        campaign_repo=campaign_repo,
        product_card_repo=product_card_repo,
        product_size_repo=product_size_repo,
        matrix_override_repo=matrix_override_repo,
        price_repo=price_repo,
        sale_repo=sale_repo,
        warehouse_mark_repo=warehouse_mark_repo,
        pinned_sku_repo=pinned_sku_repo,
        day_comment_repo=day_comment_repo,
        day_action_repo=day_action_repo,
    )


def get_cluster_analytics(
    cluster_repo: AdvertisingClusterRepoDep,
    product_card_repo: ProductCardRepoDep,
) -> ClusterAnalytics:
    """Compose the «Поиск по кластерам» service.

    The live position probe is built here rather than injected as a shared
    client: it holds no connection (it shells out to ``curl`` per request), and
    the factory is what swaps in the synthetic ranking under
    ``WB_FAKE_HARVEST`` so local dev renders the panel without touching WB.
    """
    return ClusterAnalytics(
        cluster_repo=cluster_repo,
        product_card_repo=product_card_repo,
        search_client=build_search_client(settings),
        cache_seconds=settings.wb_search_cache_seconds,
        search_dest=settings.wb_search_dest,
    )


#: Clean, injectable service type consumed by the presentation layer.
#: Ingestion has no DI wiring on purpose — it runs only in Celery tasks, which
#: compose their own session and build IngestionService directly.
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
#: The keyword-search service («Поиск по кластерам»), stored + live halves.
ClusterAnalyticsDep = Annotated[ClusterAnalytics, Depends(get_cluster_analytics)]


# --------------------------------------------------------------------------- #
# Tenancy guard
# --------------------------------------------------------------------------- #
async def require_workspace_sku(
    nm_id: int,
    workspace_id: CurrentWorkspaceId,
    product_card_repo: ProductCardRepoDep,
) -> int:
    """Ownership guard for every ``/skus/{nm_id}*`` and ``/funnel/{nm_id}`` route.

    All per-SKU repositories filter by ``nm_id`` alone (WB ids are globally
    unique), so this single choke point is what makes a foreign workspace's
    SKU behave exactly like a nonexistent one — a 404, indistinguishable from
    "no such SKU", so tenancy leaks nothing.

    Args:
        nm_id: The SKU id from the request path.
        workspace_id: The caller's validated active workspace.
        product_card_repo: The SKU -> workspace registry accessor.

    Returns:
        The same ``nm_id``, now proven to belong to the active workspace.

    Raises:
        NotFoundError: When the SKU is unregistered or owned by another
            workspace.
    """
    if not await product_card_repo.is_in_workspace(nm_id=nm_id, workspace_id=workspace_id):
        raise NotFoundError(f"SKU {nm_id} not found.")
    return nm_id


#: Path ``nm_id`` validated to belong to the caller's active workspace.
WorkspaceSku = Annotated[int, Depends(require_workspace_sku)]

__all__ = [
    "AdvertisingClusterRepoDep",
    "AdvertisingRepoDep",
    "AdvertisingSearchRepoDep",
    "AnalyticsServiceDep",
    "CampaignRepoDep",
    "ClusterAnalyticsDep",
    "CurrentWorkspaceId",
    "FunnelRepoDep",
    "MatrixOverrideRepoDep",
    "PinnedSkuRepoDep",
    "PriceRepoDep",
    "ProductCardRepoDep",
    "ProductSizeRepoDep",
    "SaleRepoDep",
    "SkuDayActionRepoDep",
    "SkuDayCommentRepoDep",
    "StockRepoDep",
    "WarehouseMarkRepoDep",
    "WorkspaceSku",
]
