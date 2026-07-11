"""Dependency-injection wiring for the Monitoring module.

Assembles the repository -> service graph from the global ``DbSession``. The
presentation layer depends only on :data:`AnalyticsServiceDep`; it never sees a
session or repository, preserving the router -> service -> repo -> model flow.

The ``deps`` package (rather than a flat ``dependencies.py``) matches the
directory layout mandated by ``architecture_rules.md`` while exposing the exact
clean dependency types described in ``di_patterns.md``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    ProductCardRepository,
    ProductSizeRepository,
    StockRepository,
)
from src.modules.monitoring.services import AnalyticsService, IngestionService


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


FunnelRepoDep = Annotated[FunnelRepository, Depends(get_funnel_repo)]
AdvertisingRepoDep = Annotated[AdvertisingRepository, Depends(get_advertising_repo)]
AdvertisingSearchRepoDep = Annotated[
    AdvertisingSearchRepository, Depends(get_advertising_search_repo)
]
StockRepoDep = Annotated[StockRepository, Depends(get_stock_repo)]
CampaignRepoDep = Annotated[CampaignRepository, Depends(get_campaign_repo)]
ProductCardRepoDep = Annotated[ProductCardRepository, Depends(get_product_card_repo)]
ProductSizeRepoDep = Annotated[ProductSizeRepository, Depends(get_product_size_repo)]
MatrixOverrideRepoDep = Annotated[MatrixOverrideRepository, Depends(get_matrix_override_repo)]


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
    )


def get_ingestion_service(
    funnel_repo: FunnelRepoDep,
    advertising_repo: AdvertisingRepoDep,
    advertising_search_repo: AdvertisingSearchRepoDep,
    stock_repo: StockRepoDep,
    campaign_repo: CampaignRepoDep,
    product_card_repo: ProductCardRepoDep,
    product_size_repo: ProductSizeRepoDep,
) -> IngestionService:
    """Compose the write-side :class:`IngestionService` from its repositories."""
    return IngestionService(
        funnel_repo=funnel_repo,
        advertising_repo=advertising_repo,
        advertising_search_repo=advertising_search_repo,
        stock_repo=stock_repo,
        campaign_repo=campaign_repo,
        product_card_repo=product_card_repo,
        product_size_repo=product_size_repo,
    )


#: Clean, injectable service types consumed by the presentation layer.
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]

__all__ = [
    "AdvertisingRepoDep",
    "AdvertisingSearchRepoDep",
    "AnalyticsServiceDep",
    "CampaignRepoDep",
    "FunnelRepoDep",
    "IngestionServiceDep",
    "MatrixOverrideRepoDep",
    "ProductCardRepoDep",
    "ProductSizeRepoDep",
    "StockRepoDep",
]
