"""DI wiring for "Summary".

The chain is shorter than every other module's because this one has no
repositories: it composes two finreports services, and it takes them from that
module's own contract rather than rebuilding them from its repositories.
"""

from typing import Annotated

from fastapi import Depends

from src.modules.finreports.contract import PnlServiceDep, SkuReportServiceDep
from src.modules.summary.services import SummaryService


def get_summary_service(pnl: PnlServiceDep, skus: SkuReportServiceDep) -> SummaryService:
    """Compose the :class:`SummaryService` from the finreports read services."""
    return SummaryService(pnl=pnl, skus=skus)


SummaryServiceDep = Annotated[SummaryService, Depends(get_summary_service)]

__all__ = ["SummaryServiceDep", "get_summary_service"]
