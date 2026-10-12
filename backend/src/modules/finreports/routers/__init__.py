"""HTTP presentation layer for the ``finreports`` module.

Five route groups behind one prefix, split because they answer different
questions of the same seller's data:

* :mod:`.pnl` — the profit-and-loss statement and the cost-price editor.
  statement («логистика») examined closely enough to file in court.
* :mod:`.harvest` — the manual «Обновить» trigger: fetch WB's finance reports
  now, for the hours the hourly schedule cannot cover.
* :mod:`.settlement_upload` — the weekly report uploaded by hand while WB's API
  holds it back, and the poll that says how it ended.
* :mod:`.balance` — the other half of the picture: what the goods that have NOT
  moved are worth, by warehouse, on one snapshot day.

All are pure pass-through routers, guarded here by the membership dependency so
carries a second, narrower guard of its own — it is ours, not a customer's.

One route sits outside the «P&L» grant: :mod:`.currency`, the unit every page
that prints money needs, whichever sections the reader was granted. It names
its own membership guard in its signature.

Domain errors raised by the services propagate to the global ``AppError``
handler in ``main.py``.
"""

from fastapi import APIRouter, Depends

from src.modules.finreports.routers.balance import router as balance_router
from src.modules.finreports.routers.currency import router as currency_router
from src.modules.finreports.routers.harvest import router as harvest_router
from src.modules.finreports.routers.pnl import router as pnl_router
from src.modules.finreports.routers.settlement_upload import router as settlement_upload_router
from src.modules.finreports.routers.window import DEFAULT_WINDOW_DAYS, resolve_window
from src.modules.organizations.contract import require_finreports

# Membership and the «P&L» grant, for every route that shows a figure.
_granted = APIRouter(dependencies=[Depends(require_finreports)])
_granted.include_router(pnl_router)
_granted.include_router(damage_router)
_granted.include_router(balance_router)
_granted.include_router(harvest_router)
_granted.include_router(settlement_upload_router)

router = APIRouter(prefix="/v1/finreports", tags=["FinReports"])
router.include_router(_granted)
router.include_router(currency_router)

__all__ = ["DEFAULT_WINDOW_DAYS", "resolve_window", "router"]
