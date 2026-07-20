"""Raw payload models for the WB Advertising surface.

Covers campaign full stats, the campaign listings (promotion/count and the v2
adverts descriptor), and the search-cluster (normquery) statistics used to
split unified-bid campaigns by display zone.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator
from pydantic_core import PydanticUseDefault

from src.integrations.wildberries.schemas.base import RawBase

# --------------------------------------------------------------------------- #
# Advertising Full Stats — GET /adv/v3/fullstats
# --------------------------------------------------------------------------- #


class WBAdvNm(RawBase):
    """Innermost ``nms`` (SKU) node inside an advertising platform bucket."""

    nm_id: int = Field(alias="nmId")
    views: int = Field(default=0)
    clicks: int = Field(default=0)
    atbs: int = Field(default=0)  # add-to-basket (add-to-cart) count
    sum: float = Field(default=0.0)
    orders: int = Field(default=0)
    sum_price: float = Field(default=0.0)  # ad-attributed order revenue (₽)


class WBAdvApp(RawBase):
    """A platform bucket (``apps``) grouping SKU stats by ``appType``."""

    app_type: int = Field(alias="appType")
    nms: list[WBAdvNm] = Field(default_factory=list)


class WBAdvDay(RawBase):
    """A single calendar day of advertising stats for one campaign."""

    stat_date: date = Field(alias="date")
    apps: list[WBAdvApp] = Field(default_factory=list)


class WBAdvCampaignStats(RawBase):
    """Top-level advertising fullstats record for one campaign id."""

    campaign_id: int = Field(alias="advertId")
    days: list[WBAdvDay] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Campaign list — GET /adv/v1/promotion/count
# Response: {"adverts": [{"type": .., "status": .., "count": ..,
#                         "advert_list": [{"advertId": .., "changeTime": ..}]}]}
# --------------------------------------------------------------------------- #


class WBAdvertRef(RawBase):
    """A single campaign reference inside a promotion-count group."""

    advert_id: int = Field(alias="advertId")


class WBCampaignGroup(RawBase):
    """A ``type`` + ``status`` group listing its campaign ids."""

    type: int = Field(alias="type")
    status: int = Field(alias="status")
    advert_list: list[WBAdvertRef] = Field(default_factory=list, alias="advert_list")


class WBCampaign(RawBase):
    """A flattened campaign descriptor: id + type + status."""

    campaign_id: int
    type: int
    status: int


# --------------------------------------------------------------------------- #
# Campaign settings — GET /api/advert/v2/adverts
#
# Verified live shape (2026-07): {"adverts": [{"id": .., "bid_type": ..,
# "status": .., "nm_settings": [{"nm_id": .., ...}], "settings": {"name": ..,
# "payment_type": .., "placements": {"search": bool, "recommendations": bool}},
# "timestamps": {...}}]}. ``bid_type`` is ``"unified"`` (единая ставка, always
# both placements) or ``"manual"`` (ручная ставка, per-placement toggles).
# --------------------------------------------------------------------------- #


class WBAdvertPlacements(RawBase):
    """Display-zone toggles of a campaign (search / recommendations)."""

    search: bool = False
    recommendations: bool = False


class WBAdvertSettings(RawBase):
    """The ``settings`` block of an advert: name, payment model, placements."""

    name: str = ""
    payment_type: str = ""
    placements: WBAdvertPlacements = Field(default_factory=WBAdvertPlacements)


class WBAdvertNmSetting(RawBase):
    """A per-SKU settings node of an advert (only the identity is consumed)."""

    nm_id: int


class WBAdvertV2(RawBase):
    """One advert (campaign) descriptor from the v2 adverts listing."""

    campaign_id: int = Field(alias="id")
    bid_type: str = ""
    status: int = 0
    settings: WBAdvertSettings = Field(default_factory=WBAdvertSettings)
    nm_settings: list[WBAdvertNmSetting] = Field(default_factory=list)

    @field_validator("nm_settings", "settings", mode="before")
    @classmethod
    def _null_to_default(cls, value: object) -> object:
        """WB sends ``null`` (not ``[]``/``{}``) on e.g. deleted campaigns."""
        if value is None:
            raise PydanticUseDefault
        return value


# --------------------------------------------------------------------------- #
# Search-cluster statistics — POST /adv/v1/normquery/stats
#
# Verified live shape (2026-07): {"items": [{"advertId": .., "nmId": ..,
# "dailyStats": [{"date": "YYYY-MM-DD", "stat": {"normQuery": .., "views": ..,
# "clicks": .., "atbs": .., "orders": .., "shks": .., "spend": ..,
# "avgPos": .., ...}}, ...one entry per day x cluster...]}]}.
# This is the SEARCH display zone only (no order revenue field), which lets the
# analytics layer split unified-bid campaigns: полки = fullstats - search.
# --------------------------------------------------------------------------- #


class WBNormQueryStat(RawBase):
    """Metrics of one search cluster on one day (search zone only)."""

    views: int = Field(default=0)
    clicks: int = Field(default=0)
    atbs: int = Field(default=0)
    orders: int = Field(default=0)
    spend: float = Field(default=0.0)


class WBNormQueryDaily(RawBase):
    """One ``dailyStats`` entry: a calendar day of one search cluster."""

    stat_date: date = Field(alias="date")
    stat: WBNormQueryStat = Field(default_factory=WBNormQueryStat)


class WBNormQueryItem(RawBase):
    """Search-cluster stats for one ``(campaign, SKU)`` pair."""

    campaign_id: int = Field(alias="advertId")
    nm_id: int = Field(alias="nmId")
    daily_stats: list[WBNormQueryDaily] = Field(default_factory=list, alias="dailyStats")

    @field_validator("daily_stats", mode="before")
    @classmethod
    def _null_to_default(cls, value: object) -> object:
        """WB sends ``null`` (not ``[]``) for pairs without search traffic."""
        if value is None:
            raise PydanticUseDefault
        return value
