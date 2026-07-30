"""Construction seam for the WildBerries clients.

Every harvest task builds its clients through these factories instead of calling
the client constructors directly. In production they return the real HTTP
clients; when ``settings.wb_fake_harvest`` is on (LOCAL only — the config guard
refuses it elsewhere) they return the synthetic stand-ins from
:mod:`src.integrations.wildberries.synthetic`, which never touch the network.

The point of the seam is that the task bodies stay byte-identical between local
and prod — only which object comes back changes, driven by one config flag — so
the two environments can never diverge in a way CI would miss.
"""

from __future__ import annotations

from src.core.config import Settings
from src.integrations.wildberries.clients.advertising import WBAdvertisingClient
from src.integrations.wildberries.clients.analytics import WBAnalyticsClient
from src.integrations.wildberries.clients.card import WBCardClient
from src.integrations.wildberries.clients.prices import WBPricesClient
from src.integrations.wildberries.clients.statistics import WBStatisticsClient
from src.integrations.wildberries.synthetic import (
    SyntheticAdvertisingClient,
    SyntheticAnalyticsClient,
    SyntheticCardClient,
    SyntheticPricesClient,
    SyntheticStatisticsClient,
)


def build_analytics_client(settings: Settings, *, token: str) -> WBAnalyticsClient:
    """The analytics (funnel + stocks + cohort) client — real or synthetic."""
    if settings.wb_fake_harvest:
        return SyntheticAnalyticsClient(settings, token=token)
    return WBAnalyticsClient(settings, token=token)


def build_advertising_client(settings: Settings, *, token: str) -> WBAdvertisingClient:
    """The advertising client — real or synthetic (the latter has no campaigns)."""
    if settings.wb_fake_harvest:
        return SyntheticAdvertisingClient(settings, token=token)
    return WBAdvertisingClient(settings, token=token)


def build_prices_client(settings: Settings, *, token: str, nm_ids: list[int]) -> WBPricesClient:
    """The seller-prices client — real or synthetic.

    ``nm_ids`` is the harvested SKU set; the synthetic client prices exactly
    those, while the real ``fetch_prices`` returns the whole account and ignores
    it (WB offers no per-SKU price filter).
    """
    if settings.wb_fake_harvest:
        return SyntheticPricesClient(settings, token=token, nm_ids=nm_ids)
    return WBPricesClient(settings, token=token)


def build_statistics_client(settings: Settings, *, token: str) -> WBStatisticsClient:
    """The account-wide sale/return feed client — real or synthetic (empty)."""
    if settings.wb_fake_harvest:
        return SyntheticStatisticsClient(settings, token=token)
    return WBStatisticsClient(settings, token=token)


def build_card_client(settings: Settings) -> WBCardClient:
    """The storefront customer-price client — real or synthetic."""
    if settings.wb_fake_harvest:
        return SyntheticCardClient(settings)
    return WBCardClient(settings)
