"""HTTP presentation layer for the ``finreports`` module.

Two route groups behind one prefix, split because they answer different
questions of the same settlement data:

* :mod:`.pnl` — the profit-and-loss statement and the cost-price editor.
  statement («логистика») examined closely enough to file in court.

Both are pure pass-through routers, guarded here by the access-token dependency
so no individual route can forget it. Domain errors raised by the services
propagate to the global ``AppError`` handler in ``main.py``.
"""

from fastapi import APIRouter, Depends

from src.core.deps import get_current_user_id
from src.modules.finreports.routers.pnl import router as pnl_router
from src.modules.finreports.routers.window import DEFAULT_WINDOW_DAYS, resolve_window

router = APIRouter(
    prefix="/v1/finreports",
    tags=["FinReports"],
    dependencies=[Depends(get_current_user_id)],
)
router.include_router(pnl_router)
router.include_router(damage_router)

__all__ = ["DEFAULT_WINDOW_DAYS", "resolve_window", "router"]
