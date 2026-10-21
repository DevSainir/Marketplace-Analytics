"""ORM models for the ``finreports`` module (PostgreSQL ``finreports`` schema).

The tables that hold WB's settlement facts (see ``docs/finreports/PNL.md``):

* :class:`FinancialReport` — one WB weekly realization report header.
* :class:`DailySettlementReport` — the provisional per-day tail in front of it,
  with the fingerprint that proves whether WB revises a day after serving it.
* :class:`ReportPublication` — when WB's API first named each report, kept
  so the lag behind WB's own site is measured rather than guessed.
* :class:`SettlementUpload` — a weekly report file the seller uploaded, whose
  rows stand in for the API's until it serves the same report.
* :class:`SettlementWatermark` — how far each workspace's settlement walk has
  actually got, which is NOT what the newest report claims to cover.
* :class:`LogisticsTransaction` — one settlement row (raw WB facts).
* :class:`SettlementDailyRollup` — the same rows pre-summed per day / SKU.
  A verified cache: every read checks it against the detail's own row counts and
  rebuilds what disagrees, so it can cost time but never correctness.

Plus the one table whose contents WB did not author:

* :class:`ProductCostPrice` — the seller's own cost of goods per SKU, the single
  input the P&L cannot verify against a WB document.
* :class:`PnlSkuExclusion` — SKUs the seller marked «Не включать в общий счёт»;
  the mark shapes the dashboard's «общий счёт» only, never a settlement fact.
* :class:`BalancePin` — the rows and columns the seller pinned to the front of
  the «Баланс по товарным остаткам» grid; ordering only, never a figure.
"""

from src.modules.finreports.models.balance_pin import BalancePin, BalancePinKind
from src.modules.finreports.models.cost_price import ProductCostPrice
from src.modules.finreports.models.daily_settlement_report import (
    DailyReportVerdict,
    DailySettlementReport,
)
from src.modules.finreports.models.financial_report import FinancialReport
from src.modules.finreports.models.logistics_transaction import LogisticsTransaction
from src.modules.finreports.models.report_publication import ReportPublication
from src.modules.finreports.models.settlement_rollup import SettlementDailyRollup
from src.modules.finreports.models.settlement_upload import (
    UPLOAD_ROW_SEQUENCE,
    SettlementUpload,
    UploadStatus,
)
from src.modules.finreports.models.settlement_watermark import SettlementWatermark
from src.modules.finreports.models.sku_exclusion import PnlSkuExclusion

__all__ = [
    "UPLOAD_ROW_SEQUENCE",
    "BalancePin",
    "BalancePinKind",
    "DailyReportVerdict",
    "DailySettlementReport",
    "FinancialReport",
    "LogisticsTransaction",
    "PnlSkuExclusion",
    "ProductCostPrice",
    "ReportPublication",
    "SettlementDailyRollup",
    "SettlementUpload",
    "SettlementWatermark",
    "UploadStatus",
]
