"""Data-access layer for the Monitoring module.

Re-exports the concrete repositories so DI wiring and services can import from
``src.modules.monitoring.repos`` directly. These classes are the sole owners of
SQL for the module — services depend on them and never issue queries.
"""

from src.modules.monitoring.repos.advertising import AdvertisingRepository
from src.modules.monitoring.repos.campaigns import CampaignRepository
from src.modules.monitoring.repos.funnel import FunnelRepository
from src.modules.monitoring.repos.products import (
    ProductCardRepository,
    ProductSizeRepository,
)
from src.modules.monitoring.repos.stocks import StockRepository

__all__ = [
    "AdvertisingRepository",
    "CampaignRepository",
    "FunnelRepository",
    "ProductCardRepository",
    "ProductSizeRepository",
    "StockRepository",
]
