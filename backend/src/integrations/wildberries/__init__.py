"""Low-level asynchronous WildBerries API clients and raw payload schemas.

Layout mirrors the WB API surfaces: one client per surface in ``clients/``
and its raw payload models in the matching ``schemas/`` module.
"""

from src.integrations.wildberries.clients import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBCardClient,
    WBContentClient,
    WBMarketplaceClient,
    WBPricesClient,
    WBPublicSearchClient,
    WBStatisticsClient,
)
from src.integrations.wildberries.factory import (
    build_advertising_client,
    build_analytics_client,
    build_card_client,
    build_marketplace_client,
    build_prices_client,
    build_search_client,
    build_statistics_client,
)

__all__ = [
    "WBAdvertisingClient",
    "WBAnalyticsClient",
    "WBCardClient",
    "WBContentClient",
    "WBMarketplaceClient",
    "WBPricesClient",
    "WBPublicSearchClient",
    "WBStatisticsClient",
    "build_advertising_client",
    "build_analytics_client",
    "build_card_client",
    "build_marketplace_client",
    "build_prices_client",
    "build_search_client",
    "build_statistics_client",
]
