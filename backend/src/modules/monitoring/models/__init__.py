"""ORM models for the Monitoring module (PostgreSQL ``monitoring`` schema).

Re-exports the concrete time-series and dimension models so callers can use the
clean import ``from src.modules.monitoring.models import SalesFunnelDaily``
regardless of the underlying file split.
"""

from src.modules.monitoring.models.advertising import AdvertisingStatDaily
from src.modules.monitoring.models.campaigns import (
    WB_STATUS_LABELS,
    WB_TYPE_LABELS,
    Campaign,
    normalize_status,
    normalize_type,
)
from src.modules.monitoring.models.products import ProductCard, ProductSize
from src.modules.monitoring.models.sales_funnel import SalesFunnelDaily
from src.modules.monitoring.models.stocks import StockSnapshot

__all__ = [
    "WB_STATUS_LABELS",
    "WB_TYPE_LABELS",
    "AdvertisingStatDaily",
    "Campaign",
    "ProductCard",
    "ProductSize",
    "SalesFunnelDaily",
    "StockSnapshot",
    "normalize_status",
    "normalize_type",
]
