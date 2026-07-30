"""Business-logic layer for the ``finreports`` module.

Mirrors the monitoring split — one write service, the rest read-only:

* :class:`IngestionService` — write side: harvest the finance report, the tariff
  calendar and the baseline dimensions into the ``finreports`` schema.
* :class:`PnlService` — read side: the settlement-basis profit-and-loss
  statement, built from the weekly report plus the seller's cost prices.
  dispute-ready evidence, which is one line of that statement examined closely.
* :class:`CostPriceService` — the module's only other write path: the seller's
  own cost of goods, the single P&L input WB cannot supply.

statement composition in :mod:`.pnl.statement`; both are I/O-free, so both are
tested against real WB payloads without a database.
"""

from src.modules.finreports.services.cost_price import CostPriceService
from src.modules.finreports.services.ingestion import IngestionService
from src.modules.finreports.services.pnl import PnlService, SkuReportService

__all__ = [
    "CostPriceService",
    "IngestionService",
    "PnlService",
    "SkuReportService",
]
