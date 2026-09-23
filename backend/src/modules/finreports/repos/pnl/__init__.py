"""P&L aggregation (facade).

Callers import from the package; the split between the aggregate's shape and its
queries is internal, exactly as the architecture rules prescribe for a layer
module that outgrew one file.
"""

from src.modules.finreports.repos.pnl.aggregate import (
    PnlGrouping,
    ReasonAmount,
    SettlementAggregate,
    SkuUnits,
)
from src.modules.finreports.repos.pnl.repository import PnlRepository
from src.modules.finreports.repos.pnl.sizes import SizeSettlement

__all__ = [
    "PnlGrouping",
    "PnlRepository",
    "ReasonAmount",
    "SettlementAggregate",
    "SizeSettlement",
    "SkuUnits",
]
