"""HTTP presentation layer for the ``advertising`` module.

Three guards on the aggregating router, so no route here can forget one:

* ``require_internal`` — the page is being built and lives only for us until it
  ships; the next-weaker guard (any paying member) would show customers a page
  whose figures have not been checked on their кабинеты.
* ``require_monitoring`` AND ``require_finreports`` — advertising is monitoring's
  data and ДРР divides it by the settlement's sales; a manager granted only one
  of the two must not be shown the other here (the «Сводка» rule).
"""

from fastapi import APIRouter, Depends

from src.modules.advertising.routers.advertising import router as advertising_router
from src.modules.organizations.contract import (
    require_finreports,
    require_internal,
    require_monitoring,
)

router = APIRouter(
    prefix="/v1",
    tags=["Advertising"],
    dependencies=[
        Depends(require_internal),
        Depends(require_monitoring),
        Depends(require_finreports),
    ],
)
router.include_router(advertising_router)

__all__ = ["router"]
