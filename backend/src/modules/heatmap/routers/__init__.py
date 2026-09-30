"""HTTP presentation layer for the ``heatmap`` module.

Two guards in front of every route, on the router so no route can forget one:
``require_monitoring`` and ``require_finreports`` — BOTH, like «Сводка»: the
grid puts the settlement's revenue and profit beside monitoring's orders and
advertising, and a manager granted one of the two must not be shown the other
here. Both resolve through ``require_member``, so a lapsed subscription is
refused before either is asked.

It was behind ``require_internal`` too while it lived under /labs; opened to
every subscribed organisation on 2026-09-30.

Writes add ``WritingAccess`` per route (:mod:`.groups`, :mod:`.norms`).
"""

from fastapi import APIRouter, Depends

from src.modules.heatmap.routers.groups import router as groups_router
from src.modules.heatmap.routers.heatmap import router as heatmap_router
from src.modules.heatmap.routers.norms import router as norms_router
from src.modules.organizations.contract import require_finreports, require_monitoring

router = APIRouter(
    prefix="/v1",
    tags=["Heatmap"],
    dependencies=[
        Depends(require_monitoring),
        Depends(require_finreports),
    ],
)
# Groups and norms first: neither may be swallowed by a parametrised route of the grid.
router.include_router(groups_router)
router.include_router(norms_router)
router.include_router(heatmap_router)

__all__ = ["router"]
