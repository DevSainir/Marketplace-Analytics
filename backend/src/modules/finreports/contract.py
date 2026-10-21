"""Public contract for the ``finreports`` module.

The stable surface other modules may consume (no horizontal imports): the read
services and their response DTOs.

The DI aliases (``PnlServiceDep``, ``SkuReportServiceDep``) are part of that
surface on purpose: a consumer must be able to obtain a service without reaching
into this module's ``deps`` package to wire its repositories by hand, which would
make every repository an implicit public name.

``PnlService`` and its ``PnlStatement`` are the module's headline output — the
settlement-basis profit-and-loss statement. The cost-price
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
    PnlSkuDaySales,
    PnlSkuReportResponse,
    PnlSkuRow,
    PnlStatement,
)
from src.modules.finreports.services import PnlService, SkuReportService

__all__ = [
    "PnlGrouping",
    "PnlResponse",
    "PnlService",
    "PnlServiceDep",
    "PnlSkuDay",
    "PnlSkuDaySales",
    "PnlSkuDays",
    "PnlSkuReportResponse",
    "PnlSkuRow",
    "PnlStatement",
    "SkuReportService",
    "SkuReportServiceDep",
]
