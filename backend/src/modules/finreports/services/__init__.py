"""Business-logic layer for the ``finreports`` module.

Mirrors the monitoring split — one write service, the rest read-only:

* :class:`IngestionService` — write side: harvest the finance report, the tariff
  calendar and the baseline dimensions into the ``finreports`` schema.
* :class:`PnlService` — read side: the settlement-basis profit-and-loss
  statement, built from the weekly report plus the seller's cost prices.
  dispute-ready evidence, which is one line of that statement examined closely.
* :class:`CostPriceService` — the module's only other write path: the seller's
  own cost of goods, the single P&L input WB cannot supply.
* :class:`HarvestControlService` — the manual «Обновить» trigger's read half:
  is a harvest running, and how far does the harvested history reach.
* :class:`BalanceService` — read side: what the UNSOLD stock is worth, per
  warehouse, on one snapshot day («Баланс по товарным остаткам»).

composition in :mod:`.pnl.statement` and the pure grid assembly in
:func:`.balance.build_balance`; all three are I/O-free, so all three are tested
against WB-shaped payloads without a database.
"""

from src.modules.finreports.services.balance import BalanceService, build_balance
from src.modules.finreports.services.cost_price import CostPriceService
from src.modules.finreports.services.harvest_control import (
    HarvestControlService,
    HarvestState,
)
from src.modules.finreports.services.ingestion import IngestionService
from src.modules.finreports.services.pnl import PnlService, SkuReportService
from src.modules.finreports.services.settlement_upload import SettlementUploadService

__all__ = [
    "BalanceService",
    "CostPriceService",
    "HarvestControlService",
    "HarvestState",
    "IngestionService",
    "PnlService",
    "SettlementUploadService",
    "SkuReportService",
    "build_balance",
]
