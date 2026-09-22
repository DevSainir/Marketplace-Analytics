"""HTTP presentation layer for the ``summary`` module.

One route behind one prefix, and two grants in front of it.

The page shows the settlement's revenue and margin beside monitoring's orders
and advertising, so it asks for BOTH module grants rather than either: a manager
allowed only one of the two would otherwise be shown the other here, and the
grant they were not given is exactly the one their owner withheld on purpose.

It restates two things WB's own cabinet does not, and both are on the page
rather than in this docstring: the weekly advertising invoice is spread over the
days the ads actually ran, and the margin is withheld entirely until every
settled SKU has a cost price.
"""

from fastapi import APIRouter, Depends

from src.modules.organizations.contract import require_finreports, require_monitoring
from src.modules.summary.routers.summary import router as summary_router

router = APIRouter(
    prefix="/v1",
    tags=["Summary"],
    # BOTH grants, not either: the page puts the settlement's revenue and
    # margin next to monitoring's orders and advertising, so a manager who
    # may see only one of the two would be shown the other here. Two
    # switches that must always agree are a bug waiting for somebody to set
    # them apart, so this route asks for both.
    dependencies=[Depends(require_monitoring), Depends(require_finreports)],
)
router.include_router(summary_router)

__all__ = ["router"]
