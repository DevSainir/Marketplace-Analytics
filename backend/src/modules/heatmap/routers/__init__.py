"""HTTP presentation layer for the ``heatmap`` module.

One guard in front of every route, on the router so no route can forget it:
``require_monitoring`` — the grid is monitoring's orders, funnel and
advertising laid out by day. The settlement's money (выручка, продажи,
прибыль, маржа) needs ``finreports`` as well, checked per request by the grid
route itself, since only a finance metric reads it: a manager granted
monitoring alone — every employee of our own organisation, as it happens —
gets the page and never the money. It resolves through ``require_member``, so
a lapsed subscription is refused before anything is asked.

It was behind ``require_internal`` too while it lived under /labs; opened to
every subscribed organisation on 2026-09-30.

Writes add ``WritingAccess`` per route (:mod:`.groups`, :mod:`.norms`).
"""

from fastapi import APIRouter, Depends

from src.modules.heatmap.routers.groups import router as groups_router
from src.modules.heatmap.routers.heatmap import router as heatmap_router
from src.modules.heatmap.routers.norms import router as norms_router
from src.modules.organizations.contract import require_monitoring

router = APIRouter(
    prefix="/v1",
    tags=["Heatmap"],
    dependencies=[
        Depends(require_monitoring),
    ],
)
# Groups and norms first: neither may be swallowed by a parametrised route of the grid.
router.include_router(groups_router)
router.include_router(norms_router)
router.include_router(heatmap_router)

__all__ = ["router"]
