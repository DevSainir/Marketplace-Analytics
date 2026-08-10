"""ORM models for the ``finreports`` module (PostgreSQL ``finreports`` schema).


* :class:`FinancialReport` — one WB weekly realization report header.

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
from src.modules.finreports.models.financial_report import FinancialReport
from src.modules.finreports.models.logistics_transaction import LogisticsTransaction
from src.modules.finreports.models.sku_exclusion import PnlSkuExclusion

__all__ = [
    "BalancePin",
    "BalancePinKind",
    "FinancialReport",
    "LogisticsTransaction",
    "PnlSkuExclusion",
    "ProductCostPrice",
]
