"""HTTP presentation layer for the ``heatmap`` module.

Two grants, each attached where its router is included so no route under it
can forget it:

* ``require_heatmap`` — the grid and its hand-set norms: «Тепловая карта» is a
  page of its own, and its grant opens every metric on it, the settlement's
  money included (that also asked for P&L until 2026-10-12).
* ``require_groups`` — the groups and the card catalogue their editor picks
  from. Groups are a control on «Сводка», P&L, «Тепловая карта» and «Реклама»,
  so whoever holds any one of those reads them; until 2026-10-12 they sat
  behind «Мониторинг», and a manager with P&L alone had no group filter.

Both resolve through ``require_member``, so a lapsed subscription is refused
before anything is asked. Writes add ``WritingAccess`` per route
(:mod:`.groups`, :mod:`.norms`).

It was behind ``require_internal`` too while it lived under /labs; opened to
every subscribed organisation on 2026-09-30.
"""

from fastapi import APIRouter, Depends

from src.modules.heatmap.routers.groups import router as groups_router
from src.modules.heatmap.routers.heatmap import catalog_router
from src.modules.heatmap.routers.heatmap import router as heatmap_router
from src.modules.heatmap.routers.norms import router as norms_router
from src.modules.organizations.contract import require_groups, require_heatmap

router = APIRouter(prefix="/v1", tags=["Heatmap"])
# Groups, norms and the catalogue first: none may be swallowed by a
# parametrised route of the grid.
router.include_router(groups_router, dependencies=[Depends(require_groups)])
router.include_router(catalog_router, dependencies=[Depends(require_groups)])
router.include_router(norms_router, dependencies=[Depends(require_heatmap)])
router.include_router(heatmap_router, dependencies=[Depends(require_heatmap)])

__all__ = ["router"]
