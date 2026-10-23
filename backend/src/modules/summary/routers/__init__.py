"""HTTP presentation layer for the ``summary`` module.

One route behind one prefix, and the "Summary" grant in front of it.

The page shows the settlement's revenue and margin beside monitoring's orders
and advertising. It asked for BOTH the "Monitoring" and P&L grants until
2026-10-12; since then every page of the header is a grant of its own, and
this one opens the whole page — an owner who gives "Summary" is deciding about
its money too. Existing managers got it exactly where they held both before.

It restates two things WB's own seller portal does not, and both are on the page
rather than in this docstring: the weekly advertising invoice is spread over the
days the ads actually ran, and the margin is withheld entirely until every
settled SKU has a cost price.
"""

from fastapi import APIRouter, Depends

from src.modules.organizations.contract import require_summary
from src.modules.summary.routers.summary import router as summary_router

router = APIRouter(
    prefix="/v1",
    tags=["Summary"],
    dependencies=[Depends(require_summary)],
)
router.include_router(summary_router)

__all__ = ["router"]
