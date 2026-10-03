"""DI wiring for «Реклама».

No repositories of its own: advertising facts come through the monitoring
contract as plain loaders, and sales through the finreports services, taken
from that module's own contract rather than rebuilt from its repositories.
"""

from typing import Annotated

from fastapi import Depends

from src.modules.advertising.services import AdvertisingService
from src.modules.finreports.contract import PnlServiceDep, SkuReportServiceDep


def get_advertising_service(pnl: PnlServiceDep, skus: SkuReportServiceDep) -> AdvertisingService:
    """Compose the :class:`AdvertisingService` from the finreports read services."""
    return AdvertisingService(pnl=pnl, skus=skus)


AdvertisingServiceDep = Annotated[AdvertisingService, Depends(get_advertising_service)]

__all__ = ["AdvertisingServiceDep", "get_advertising_service"]
