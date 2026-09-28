"""HTTP presentation layer for the ``heatmap`` module.

Three guards in front of every route, on the router so no route can forget one:

* ``require_internal`` — the page lives under /labs while it is being tried
  out, and the API refuses it to everyone the SPA does;
* ``require_monitoring`` and ``require_finreports`` — BOTH, like «Сводка»: the
  grid puts the settlement's revenue and profit beside monitoring's orders and
  advertising, and a manager granted one of the two must not be shown the other
  here.

Writes add ``WritingAccess`` per route (:mod:`.groups`).
"""

from fastapi import APIRouter, Depends

from src.modules.heatmap.routers.groups import router as groups_router
from src.modules.heatmap.routers.heatmap import router as heatmap_router
from src.modules.organizations.contract import (
    require_finreports,
    require_internal,
    require_monitoring,
)

router = APIRouter(
    prefix="/v1",
    tags=["Heatmap"],
    dependencies=[
        Depends(require_internal),
        Depends(require_monitoring),
        Depends(require_finreports),
    ],
)
# Groups first: `/groups` must not be swallowed by a parametrised route of the grid.
router.include_router(groups_router)
router.include_router(heatmap_router)

__all__ = ["router"]
