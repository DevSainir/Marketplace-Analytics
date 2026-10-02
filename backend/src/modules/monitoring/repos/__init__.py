"""Data-access layer for the Monitoring module.

Re-exports the concrete repositories so DI wiring and services can import from
``src.modules.monitoring.repos`` directly. These classes are the sole owners of
SQL for the module — services depend on them and never issue queries.
"""

from src.modules.monitoring.repos.advertising import AdvertisingRepository
from src.modules.monitoring.repos.advertising_clusters import AdvertisingClusterRepository
from src.modules.monitoring.repos.advertising_search import AdvertisingSearchRepository
from src.modules.monitoring.repos.advertising_write_offs import AdvertisingWriteOffRepository
from src.modules.monitoring.repos.campaigns import CampaignRepository
from src.modules.monitoring.repos.day_actions import SkuDayActionRepository
from src.modules.monitoring.repos.fbs_warehouses import FbsWarehouseRepository
from src.modules.monitoring.repos.funnel import FunnelRepository
from src.modules.monitoring.repos.matrix_override import MatrixOverrideRepository
from src.modules.monitoring.repos.pinned_skus import PinnedSkuRepository
from src.modules.monitoring.repos.prices import PriceRepository
from src.modules.monitoring.repos.products import (
    ProductCardRepository,
    ProductSizeRepository,
)
from src.modules.monitoring.repos.reviews import EventDraft, KnownReview, ReviewRepository
from src.modules.monitoring.repos.sales import SaleRepository
from src.modules.monitoring.repos.sku_day_comment import SkuDayCommentRepository
from src.modules.monitoring.repos.stocks import StockRepository

__all__ = [
    "AdvertisingClusterRepository",
    "AdvertisingRepository",
    "AdvertisingSearchRepository",
    "AdvertisingWriteOffRepository",
    "CampaignRepository",
    "EventDraft",
    "FbsWarehouseRepository",
    "FunnelRepository",
    "KnownReview",
    "MatrixOverrideRepository",
    "PinnedSkuRepository",
    "PriceRepository",
    "ProductCardRepository",
    "ProductSizeRepository",
    "ReviewRepository",
    "SaleRepository",
    "SkuDayActionRepository",
    "SkuDayCommentRepository",
    "StockRepository",
]
