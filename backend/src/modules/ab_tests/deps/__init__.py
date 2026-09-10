"""Dependency-injection wiring for the A/B-tests module.

Assembles the repository -> service graph from the global ``DbSession``. The
router depends only on :data:`AbTestCatalogServiceDep` and the workspace id.

The WB content client is built per request from the workspace's own token: a
test writes to that workspace's card, so the credential must come from the same
tenancy check as the data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.config import settings
from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.integrations.wildberries import WBContentClient
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    SnapshotRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.catalog import AbTestCatalogService
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.skus import SkuCatalogue
from src.modules.ab_tests.services.storage import MediaStore, build_media_store
from src.modules.ab_tests.services.variants import VariantCatalogService
from src.modules.workspaces.contract import CurrentWorkspaceId, load_workspace_token_bundle


def get_media_store() -> MediaStore:
    """Provide the configured media store — object storage, or a local fallback."""
    return build_media_store(settings)


MediaStoreDep = Annotated[MediaStore, Depends(get_media_store)]


async def get_installer(
    session: DbSession,
    workspace_id: CurrentWorkspaceId,
    media_store: MediaStoreDep,
) -> VariantInstaller:
    """Provide an installer bound to the workspace's own WB content token.

    Raises:
        ValidationError: If the workspace has no token that reaches the Content
            surface — without it a test could be started but never rotated, so
            it is refused up front rather than at the first swap.
    """
    bundle = await load_workspace_token_bundle(session, workspace_id=workspace_id)
    token = (bundle.content or bundle.analytics) if bundle else ""
    if not token:
        raise ValidationError(
            "Для А/Б-тестов нужен токен с доступом к «Контенту» — укажите токен в настройках."
        )
    return VariantInstaller(
        content_client=WBContentClient(settings, token=token), media_store=media_store
    )


InstallerDep = Annotated[VariantInstaller, Depends(get_installer)]


def get_sku_catalogue(session: DbSession) -> SkuCatalogue:
    """Provide the module's catalogue lookup, bound to the request session."""
    return SkuCatalogue(session)


SkuCatalogueDep = Annotated[SkuCatalogue, Depends(get_sku_catalogue)]


def get_test_repo(session: DbSession) -> AbTestRepository:
    """Provide an :class:`AbTestRepository` bound to the request session."""
    return AbTestRepository(session)


def get_variant_repo(session: DbSession) -> VariantRepository:
    """Provide a :class:`VariantRepository` bound to the request session."""
    return VariantRepository(session)


def get_exposure_repo(session: DbSession) -> ExposureRepository:
    """Provide an :class:`ExposureRepository` bound to the request session."""
    return ExposureRepository(session)


def get_snapshot_repo(session: DbSession) -> SnapshotRepository:
    """Provide a :class:`SnapshotRepository` bound to the request session."""
    return SnapshotRepository(session)


def get_stat_repo(session: DbSession) -> WindowRepository:
    """Provide a :class:`WindowRepository` bound to the request session."""
    return WindowRepository(session)


def get_catalog_service(
    tests: Annotated[AbTestRepository, Depends(get_test_repo)],
    variants: Annotated[VariantRepository, Depends(get_variant_repo)],
    exposures: Annotated[ExposureRepository, Depends(get_exposure_repo)],
    stats: Annotated[WindowRepository, Depends(get_stat_repo)],
    snapshots: Annotated[SnapshotRepository, Depends(get_snapshot_repo)],
    media_store: MediaStoreDep,
) -> AbTestCatalogService:
    """Provide the module's request-scoped service."""
    return AbTestCatalogService(
        tests=tests,
        variants=variants,
        exposures=exposures,
        stats=stats,
        snapshots=snapshots,
        media_store=media_store,
    )


AbTestCatalogServiceDep = Annotated[AbTestCatalogService, Depends(get_catalog_service)]


def get_variant_service(
    tests: Annotated[AbTestRepository, Depends(get_test_repo)],
    variants: Annotated[VariantRepository, Depends(get_variant_repo)],
    stats: Annotated[WindowRepository, Depends(get_stat_repo)],
    media_store: MediaStoreDep,
) -> VariantCatalogService:
    """Provide the photo-side service, bound to the request session."""
    return VariantCatalogService(
        tests=tests, variants=variants, stats=stats, media_store=media_store
    )


VariantServiceDep = Annotated[VariantCatalogService, Depends(get_variant_service)]

__all__ = [
    "AbTestCatalogServiceDep",
    "InstallerDep",
    "MediaStoreDep",
    "SkuCatalogueDep",
    "VariantServiceDep",
    "get_catalog_service",
    "get_installer",
    "get_media_store",
    "get_sku_catalogue",
    "get_variant_service",
]
