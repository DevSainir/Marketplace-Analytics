"""ORM models for the ``finreports`` module (PostgreSQL ``finreports`` schema).


* :class:`FinancialReport` — one WB weekly realization report header.
"""

from src.modules.finreports.models.financial_report import FinancialReport
from src.modules.finreports.models.logistics_transaction import LogisticsTransaction

__all__ = [
    "FinancialReport",
    "LogisticsTransaction",
]
