"""Typed representations of raw WildBerries API responses.

One module per WB API surface (mirroring ``..clients``): analytics (funnel +
stocks), advertising, content (product cards), prices (seller prices), card
(public storefront), and statistics (per-sale records). Every model is
re-exported here so callers keep importing from
``src.integrations.wildberries.schemas``.
"""

from src.integrations.wildberries.schemas.advertising import (
    WBAdvApp,
    WBAdvCampaignStats,
    WBAdvDay,
    WBAdvertNmSetting,
    WBAdvertPlacements,
    WBAdvertRef,
    WBAdvertSettings,
    WBAdvertV2,
    WBAdvNm,
    WBCampaign,
    WBCampaignGroup,
    WBNormQueryDaily,
    WBNormQueryItem,
    WBNormQueryStat,
)
from src.integrations.wildberries.schemas.analytics import (
    WBFunnelAggregateRow,
    WBFunnelAggregateSelected,
    WBFunnelAggregateStatistic,
    WBFunnelHistoryDay,
    WBFunnelHistoryProduct,
    WBFunnelHistoryRow,
    WBStockRow,
)
from src.integrations.wildberries.schemas.card import (
    WBCardPrice,
    WBCardProduct,
    WBCardSizePrice,
)
from src.integrations.wildberries.schemas.content import WBCard, WBCardDimensions, WBCardSize
from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.integrations.wildberries.schemas.prices import WBPriceGood, WBPriceSize
from src.integrations.wildberries.schemas.statistics import WBSaleRecord
)

__all__ = [
    "WBAdvApp",
    "WBAdvCampaignStats",
    "WBAdvDay",
    "WBAdvNm",
    "WBAdvertNmSetting",
    "WBAdvertPlacements",
    "WBAdvertRef",
    "WBAdvertSettings",
    "WBAdvertV2",
    "WBCampaign",
    "WBCampaignGroup",
    "WBCard",
    "WBCardDimensions",
    "WBCardPrice",
    "WBCardProduct",
    "WBCardSize",
    "WBCardSizePrice",
    "WBFunnelAggregateRow",
    "WBFunnelAggregateSelected",
    "WBFunnelAggregateStatistic",
    "WBFunnelHistoryDay",
    "WBFunnelHistoryProduct",
    "WBFunnelHistoryRow",
    "WBNormQueryDaily",
    "WBNormQueryItem",
    "WBNormQueryStat",
    "WBPriceGood",
    "WBPriceSize",
    "WBReportDetailRow",
    "WBSaleRecord",
    "WBStockRow",
]
