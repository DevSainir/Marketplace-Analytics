"""Profit-and-loss reporting for ``finreports`` (facade)."""

from src.modules.finreports.services.pnl.service import PnlService
from src.modules.finreports.services.pnl.sku_report import build_sku_report, build_sku_row
from src.modules.finreports.services.pnl.sku_service import SkuReportService
from src.modules.finreports.services.pnl.statement import build_statement

__all__ = [
    "PnlService",
    "SkuReportService",
    "build_sku_report",
    "build_sku_row",
    "build_statement",
]
