"""HTTP presentation layer for the ``finreports`` module.

Four route groups behind one prefix, split because they answer different
questions of the same seller's data:

* :mod:`.pnl` — the profit-and-loss statement and the cost-price editor.
  statement («логистика») examined closely enough to file in court.
* :mod:`.harvest` — the manual «Обновить» trigger: fetch WB's finance reports
  now, for the hours the hourly schedule cannot cover.
* :mod:`.balance` — the other half of the picture: what the goods that have NOT
  moved are worth, by warehouse, on one snapshot day.

All are pure pass-through routers, guarded here by the membership dependency so
carries a second, narrower guard of its own — it is ours, not a customer's.

Domain errors raised by the services propagate to the global ``AppError``
handler in ``main.py``.
"""

from fastapi import APIRouter, Depends

from src.modules.finreports.routers.balance import router as balance_router
from src.modules.finreports.routers.harvest import router as harvest_router
from src.modules.finreports.routers.pnl import router as pnl_router
from src.modules.finreports.routers.window import DEFAULT_WINDOW_DAYS, resolve_window
from src.modules.organizations.contract import require_finreports

router = APIRouter(
    prefix="/v1/finreports",
    tags=["FinReports"],
    # Membership and the «Прибыли и убытки» grant, for every route below.
    dependencies=[Depends(require_finreports)],
)
router.include_router(pnl_router)
router.include_router(damage_router)
router.include_router(balance_router)
router.include_router(harvest_router)

__all__ = ["DEFAULT_WINDOW_DAYS", "resolve_window", "router"]
