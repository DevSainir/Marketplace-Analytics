"""DI wiring for the heatmap.

The read service composes its own repository with two finreports services,
taken from that module's contract rather than rebuilt from its repositories —
the same arrangement «Сводка» uses.
"""

from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
from src.modules.finreports.contract import PnlServiceDep, SkuReportServiceDep
from src.modules.heatmap.repos import SkuGroupRepository, SkuNormRepository
from src.modules.heatmap.services import HeatmapService, SkuGroupService, SkuNormService


def get_group_repo(session: DbSession) -> SkuGroupRepository:
    """Provide a request-scoped group repository."""
    return SkuGroupRepository(session)


SkuGroupRepoDep = Annotated[SkuGroupRepository, Depends(get_group_repo)]


def get_heatmap_service(
    groups: SkuGroupRepoDep, pnl: PnlServiceDep, skus: SkuReportServiceDep
) -> HeatmapService:
    """Compose the :class:`HeatmapService`."""
    return HeatmapService(groups=groups, pnl=pnl, skus=skus)


def get_group_service(groups: SkuGroupRepoDep) -> SkuGroupService:
    """Compose the :class:`SkuGroupService`."""
    return SkuGroupService(groups)


def get_norm_service(session: DbSession) -> SkuNormService:
    """Compose the :class:`SkuNormService`."""
    return SkuNormService(SkuNormRepository(session))


HeatmapServiceDep = Annotated[HeatmapService, Depends(get_heatmap_service)]
SkuGroupServiceDep = Annotated[SkuGroupService, Depends(get_group_service)]
SkuNormServiceDep = Annotated[SkuNormService, Depends(get_norm_service)]

__all__ = [
    "HeatmapServiceDep",
    "SkuGroupRepoDep",
    "SkuGroupServiceDep",
    "SkuNormServiceDep",
    "get_group_repo",
    "get_group_service",
    "get_heatmap_service",
    "get_norm_service",
]
