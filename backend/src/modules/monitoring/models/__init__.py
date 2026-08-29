"""ORM models for the Monitoring module (PostgreSQL ``monitoring`` schema).

Re-exports the concrete time-series and dimension models so callers can use the
clean import ``from src.modules.monitoring.models import SalesFunnelDaily``
regardless of the underlying file split.
"""

from src.modules.monitoring.models.advertising import (
    CLUSTER_MAX_LENGTH,
    AdvertisingClusterStatDaily,
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
)
from src.modules.monitoring.models.campaigns import (
    WB_STATUS_LABELS,
    WB_TYPE_LABELS,
    Campaign,
    normalize_status,
    normalize_type,
)
from src.modules.monitoring.models.day_actions import SkuDayAction
from src.modules.monitoring.models.fbs_warehouses import LABEL_MAX_LENGTH, FbsWarehouse
from src.modules.monitoring.models.matrix_override import MatrixOverride
from src.modules.monitoring.models.pinned_skus import PinnedSku
from src.modules.monitoring.models.prices import PriceSnapshot
from src.modules.monitoring.models.products import ProductCard, ProductSize
from src.modules.monitoring.models.sales import SaleRecord
from src.modules.monitoring.models.sales_funnel import SalesFunnelDaily
from src.modules.monitoring.models.sku_day_comment import SkuDayComment
from src.modules.monitoring.models.stocks import StockSnapshot
from src.modules.monitoring.models.warehouse_marks import WarehouseMark

__all__ = [
    "CLUSTER_MAX_LENGTH",
    "LABEL_MAX_LENGTH",
    "WB_STATUS_LABELS",
    "WB_TYPE_LABELS",
    "AdvertisingClusterStatDaily",
    "AdvertisingSearchStatDaily",
    "AdvertisingStatDaily",
    "Campaign",
    "FbsWarehouse",
    "MatrixOverride",
    "PinnedSku",
    "PriceSnapshot",
    "ProductCard",
    "ProductSize",
    "SaleRecord",
    "SalesFunnelDaily",
    "SkuDayAction",
    "SkuDayComment",
    "StockSnapshot",
    "WarehouseMark",
    "normalize_status",
    "normalize_type",
]
