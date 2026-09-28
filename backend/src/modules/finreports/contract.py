"""Public contract for the ``finreports`` module.

The stable surface other modules may consume (no horizontal imports): the read

The DI aliases (``PnlServiceDep``, ``SkuReportServiceDep``) are part of that
surface on purpose: a consumer must be able to obtain a service without reaching
into this module's ``deps`` package to wire its repositories by hand, which would
make every repository an implicit public name.

``PnlService`` and its ``PnlStatement`` are the module's headline output — the
of it («логистика») examined closely enough to file in court. The cost-price
service is deliberately NOT exported: those figures are the seller's own
commercial input, edited through this module's own HTTP surface, and nothing
outside it has a reason to write them.
"""

from src.modules.finreports.deps import PnlServiceDep, SkuReportServiceDep
from src.modules.finreports.repos import PnlGrouping
from src.modules.finreports.schemas import (
    PnlResponse,
    PnlSkuDay,
    PnlSkuDays,
    PnlSkuReportResponse,
    PnlSkuRow,
    PnlStatement,
)
    LogisticsPricing,
)

__all__ = [
    "LogisticsPricing",
    "PnlGrouping",
    "PnlResponse",
    "PnlService",
    "PnlServiceDep",
    "PnlSkuDay",
    "PnlSkuDays",
    "PnlSkuReportResponse",
    "PnlSkuRow",
    "PnlStatement",
    "SkuReportService",
    "SkuReportServiceDep",
]
