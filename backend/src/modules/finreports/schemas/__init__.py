"""Pydantic DTOs for the ``finreports`` presentation layer.

Read-only projections the services return to the routers — never a 1:1
mirror of the ORM rows (the service maps models onto these).
"""

from src.modules.finreports.schemas.balance import (
    BalanceCell,
    BalancePinInput,
    BalanceResponse,
    BalanceSkuRow,
)
from src.modules.finreports.schemas.cost_price import (
    CostPriceBulkInput,
    CostPriceImportIssue,
    CostPriceImportResponse,
    CostPriceInput,
    CostPriceItem,
    CostPriceListResponse,
    CostPriceSaveResponse,
)
from src.modules.finreports.schemas.currency import SettlementCurrencyResponse
from src.modules.finreports.schemas.harvest import (
    FreshnessCheckOut,
    HarvestStateResponse,
    HarvestTriggerResponse,
    LatestReportOut,
    ReportPeriodOut,
)
from src.modules.finreports.schemas.pnl import (
    PnlResponse,
    PnlSection,
    PnlStatement,
    ReasonShare,
    WeekPeriod,
    WeeksResponse,
)
from src.modules.finreports.schemas.settlement_upload import SettlementUploadOut
from src.modules.finreports.schemas.size_report import (
    PnlSizeRow,
    PnlSizesResponse,
)
from src.modules.finreports.schemas.sku_days import PnlSkuDay, PnlSkuDays, PnlSkuDaySales
from src.modules.finreports.schemas.sku_report import (
    PnlDashboard,
    PnlSkuReportResponse,
    PnlSkuRow,
    SkuExclusionInput,
    SkuPenalty,
)

__all__ = [
    "BalanceCell",
    "BalancePinInput",
    "BalanceResponse",
    "BalanceSkuRow",
    "CostPriceBulkInput",
    "CostPriceImportIssue",
    "CostPriceImportResponse",
    "CostPriceInput",
    "CostPriceItem",
    "CostPriceListResponse",
    "CostPriceSaveResponse",
    "FreshnessCheckOut",
    "HarvestStateResponse",
    "HarvestTriggerResponse",
    "LatestReportOut",
    "PnlDashboard",
    "PnlResponse",
    "PnlSection",
    "PnlSizeRow",
    "PnlSizesResponse",
    "PnlSkuDay",
    "PnlSkuDaySales",
    "PnlSkuDays",
    "PnlSkuReportResponse",
    "PnlSkuRow",
    "PnlStatement",
    "ReasonShare",
    "ReportPeriodOut",
    "SettlementCurrencyResponse",
    "SettlementUploadOut",
    "SkuExclusionInput",
    "SkuPenalty",
    "WeekPeriod",
    "WeeksResponse",
]
