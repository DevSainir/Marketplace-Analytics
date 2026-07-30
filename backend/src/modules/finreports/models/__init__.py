"""ORM models for the ``finreports`` module (PostgreSQL ``finreports`` schema).


* :class:`FinancialReport` — one WB weekly realization report header.

Plus the one table whose contents WB did not author:

* :class:`ProductCostPrice` — the seller's own cost of goods per SKU, the single
  input the P&L cannot verify against a WB document.
"""

from src.modules.finreports.models.cost_price import ProductCostPrice
from src.modules.finreports.models.financial_report import FinancialReport
from src.modules.finreports.models.logistics_transaction import LogisticsTransaction

__all__ = [
    "FinancialReport",
    "LogisticsTransaction",
    "ProductCostPrice",
]
