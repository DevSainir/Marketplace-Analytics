"""HTTP presentation layer for the ``summary`` module.

One route behind one prefix, and one guard in front of it.

**The guard is ``require_internal``, and the next weaker one would be wrong.**
This surface lives at `/labs/summary` and restates the margin: it swaps WB's
weekly advertising invoice for the burn the advertising statistics actually
recorded, and it withholds the margin entirely until every settled SKU has a
cost price. Neither choice has been explained to a customer yet, and a figure a
seller cannot reconcile against WB's own cabinet is worse than no figure. When
it ships, this becomes a module grant like «Мониторинг» and «Отчёты».
"""

from fastapi import APIRouter, Depends

from src.modules.organizations.contract import require_internal
from src.modules.summary.routers.summary import router as summary_router

router = APIRouter(
    prefix="/v1",
    tags=["Summary"],
    dependencies=[Depends(require_internal)],
)
router.include_router(summary_router)

__all__ = ["router"]
