"""Write-side ingestion package for the Monitoring module.

Consumes *raw, nested* WildBerries payloads (from the integration clients),
flattens the ``apps -> nms`` / conversion trees into clean relational records,
and persists them through repositories. Timestamps are normalized to Moscow
time (UTC+3) per the WB API global constraint before persistence.

One fact family per module, each with a single responsibility:

* :mod:`~src.modules.monitoring.services.ingestion.funnel` — daily organic
  funnel history, order-date cohorts, historical backfill.
* :mod:`~src.modules.monitoring.services.ingestion.advertising` — fullstats
  trees, campaign metadata, SEARCH-zone normquery slices.
* :mod:`~src.modules.monitoring.services.ingestion.stocks` — size x warehouse
  stock snapshots.
* :mod:`~src.modules.monitoring.services.ingestion.prices` — daily
  seller/customer price snapshots.
* :mod:`~src.modules.monitoring.services.ingestion.sales` — per-item
  sale/return records.
* :mod:`~src.modules.monitoring.services.ingestion.catalog` — product-card and
  size dimensions.
* :mod:`~src.modules.monitoring.services.ingestion.service` — the
  :class:`IngestionService` facade orchestrating them (``ingest_all``).

This ``__init__`` is the package facade: Celery tasks and the DI wiring keep
importing :class:`IngestionService` exactly as they did from the former flat
``services/ingestion.py`` module.
"""

from src.modules.monitoring.services.ingestion.advertising import AdvertisingIngestion
from src.modules.monitoring.services.ingestion.catalog import CatalogIngestion
from src.modules.monitoring.services.ingestion.funnel import FunnelIngestion
from src.modules.monitoring.services.ingestion.prices import PriceIngestion
from src.modules.monitoring.services.ingestion.sales import SalesIngestion
from src.modules.monitoring.services.ingestion.service import IngestionService
from src.modules.monitoring.services.ingestion.stocks import StockIngestion

__all__ = [
    "AdvertisingIngestion",
    "CatalogIngestion",
    "FunnelIngestion",
    "IngestionService",
    "PriceIngestion",
    "SalesIngestion",
    "StockIngestion",
]
