"""Low-level asynchronous WildBerries API clients, one per WB API surface."""

from src.integrations.wildberries.clients.advertising import WBAdvertisingClient
from src.integrations.wildberries.clients.analytics import WBAnalyticsClient
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.clients.card import WBCardClient
from src.integrations.wildberries.clients.content import WBContentClient
from src.integrations.wildberries.clients.finance_reports import (
    ReportPeriod,
    WBFinanceReportsClient,
)
from src.integrations.wildberries.clients.marketplace import WBMarketplaceClient
)
from src.integrations.wildberries.clients.prices import WBPricesClient
from src.integrations.wildberries.clients.statistics import WBStatisticsClient

__all__ = [
    "BaseWBClient",
    "ReportPeriod",
    "WBAdvertisingClient",
    "WBAnalyticsClient",
    "WBCardClient",
    "WBContentClient",
    "WBFinanceReportsClient",
    "WBMarketplaceClient",
    "WBPricesClient",
    "WBStatisticsClient",
]
