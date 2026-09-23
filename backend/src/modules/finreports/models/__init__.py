"""ORM models for the ``finreports`` module (PostgreSQL ``finreports`` schema).


* :class:`FinancialReport` — one WB weekly realization report header.
* :class:`DailySettlementReport` — the provisional per-day tail in front of it,
  with the fingerprint that proves whether WB revises a day after serving it.
* :class:`SettlementWatermark` — how far each workspace's settlement walk has
  actually got, which is NOT what the newest report claims to cover.
* :class:`SettlementDailyRollup` — the same rows pre-summed per день / артикул.
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
from src.modules.finreports.models.settlement_rollup import SettlementDailyRollup
from src.modules.finreports.models.settlement_watermark import SettlementWatermark
from src.modules.finreports.models.sku_exclusion import PnlSkuExclusion

__all__ = [
    "BalancePin",
    "BalancePinKind",
    "DailyReportVerdict",
    "DailySettlementReport",
    "FinancialReport",
    "LogisticsTransaction",
    "PnlSkuExclusion",
    "ProductCostPrice",
    "SettlementDailyRollup",
    "SettlementWatermark",
]
