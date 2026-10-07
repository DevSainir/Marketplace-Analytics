"""HTTP presentation layer for the ``advertising`` module.

Two guards on the aggregating router, so no route here can forget one:

* ``require_internal`` — the page is being built and lives only for us until it
  ships; the next-weaker guard (any paying member) would show customers a page
  whose figures have not been checked on their кабинеты.
* ``require_monitoring`` — advertising is monitoring's data.

The finreports grant is NOT a guard here, by the owner's decision of
2026-10-07: every member of our own organisation reads the whole page, sales
and ДРР included, though three of its managers hold monitoring alone. That is
an exception to the «Сводка» rule (a manager not granted «Отчёты» sees no
sale) made for this page only; re-read it before the page ships to customers,
whose owners grant modules expecting that rule to hold.
"""

from fastapi import APIRouter, Depends

from src.modules.advertising.routers.advertising import router as advertising_router
from src.modules.organizations.contract import require_internal, require_monitoring

router = APIRouter(
    prefix="/v1",
    tags=["Advertising"],
    dependencies=[
        Depends(require_internal),
        Depends(require_monitoring),
    ],
)
router.include_router(advertising_router)

__all__ = ["router"]
