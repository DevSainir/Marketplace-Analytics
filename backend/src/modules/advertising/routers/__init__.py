"""HTTP presentation layer for the ``advertising`` module.

One guard on the aggregating router, so no route here can forget it:
``require_advertising`` — the «Реклама» grant, open to every subscriber since
2026-10-10.

It is a switch of its own rather than «Мониторинг»'s, by the owner's decision
of that day. The page shows sales and ДРР от продаж, so under the «Сводка» rule
a manager holding monitoring alone could not have read it; a separate grant lets
an owner decide about this page directly. It is on by default — the migration
that introduced it backfilled every membership and invitation — so nobody who
read the page lost it, and narrowing is something an owner does deliberately.
"""

from fastapi import APIRouter, Depends

from src.modules.advertising.routers.advertising import router as advertising_router
from src.modules.organizations.contract import require_advertising

router = APIRouter(
    prefix="/v1",
    tags=["Advertising"],
    dependencies=[Depends(require_advertising)],
)
router.include_router(advertising_router)

__all__ = ["router"]
