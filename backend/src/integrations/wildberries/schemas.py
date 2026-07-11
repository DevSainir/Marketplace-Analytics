"""Typed representations of raw WildBerries API responses.

These Pydantic models mirror the *nested* shape WB returns on the wire. They
are deliberately permissive (``extra="ignore"``) because WB frequently adds
fields. The Monitoring module's ingestion service flattens these trees into the
clean relational records defined by its own ORM models — the raw shapes never
leak past the integration boundary.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticUseDefault


class _RawBase(BaseModel):
    """Base config for all raw WB payload models."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --------------------------------------------------------------------------- #
# Sales Funnel (Organics) — DAILY history
# POST /api/analytics/v3/sales-funnel/products/history
#
# Verified live shape (2026-07): a top-level LIST, one node per product::
#   [
#     {"product": {"nmId": .., "title": .., "vendorCode": .., ...},
#      "history": [
#         {"date": "2026-06-29", "openCount": .., "cartCount": ..,
#          "orderCount": .., "orderSum": .., "buyoutCount": ..,
#          "buyoutPercent": .., "addToCartConversion": ..,
#          "cartToOrderConversion": .., "addToWishlistCount": ..},
#         ...one entry per calendar day...
#      ]},
#     ...
#   ]
# This is the TRUE per-day series that powers baseline-demand normalization.
# --------------------------------------------------------------------------- #
class WBFunnelHistoryDay(_RawBase):
    """A single calendar day of organic funnel metrics for one product."""

    stat_date: date = Field(alias="date")
    open_count: int = Field(default=0, alias="openCount")
    cart_count: int = Field(default=0, alias="cartCount")
    order_count: int = Field(default=0, alias="orderCount")
    order_sum: float = Field(default=0.0, alias="orderSum")
    buyout_count: int = Field(default=0, alias="buyoutCount")
    buyout_sum: float = Field(default=0.0, alias="buyoutSum")
    add_to_wishlist: int = Field(default=0, alias="addToWishlistCount")
    # WB returns these conversions directly (as whole-number percents).
    cart_conversion: float = Field(default=0.0, alias="addToCartConversion")
    order_conversion: float = Field(default=0.0, alias="cartToOrderConversion")
    buyout_conversion: float = Field(default=0.0, alias="buyoutPercent")


class WBFunnelHistoryProduct(_RawBase):
    """The ``product`` identity block of a funnel-history node."""

    nm_id: int = Field(alias="nmId")


class WBFunnelHistoryRow(_RawBase):
    """One product node holding its full per-day funnel ``history``."""

    product: WBFunnelHistoryProduct
    history: list[WBFunnelHistoryDay] = Field(default_factory=list)

    @property
    def nm_id(self) -> int:
        """SKU identifier of this product."""
        return self.product.nm_id


# --------------------------------------------------------------------------- #
# Content — product cards
# POST /content/v2/get/cards/list
#
# Verified live shape (2026-07): {"cards": [ {nmID, vendorCode, title,
# brand, sizes: [{chrtID, techSize, wbSize, skus}], ...}, ... ],
# "cursor": {updatedAt, nmID, total}}. This is the authoritative source for
# the human-readable vendor code (``Артикул продавца``) and size label
# (``Размер вещи`` == ``techSize``); the stocks endpoint carries only chrtID.
# --------------------------------------------------------------------------- #
class WBCardSize(_RawBase):
    """One size variant of a product card.

    ``tech_size`` is WB's human size label (the seller-portal "Размер вещи"
    column, e.g. ``"52/170-177"`` / ``"L"`` / ``"42"``); ``wb_size`` is WB's
    alternate scale (e.g. ``"2XL/ 170-177"`` / ``"46"``). ``chrt_id`` is the
    join key back to the label-less stock rows.
    """

    chrt_id: int = Field(alias="chrtID")
    tech_size: str = Field(default="", alias="techSize")
    wb_size: str = Field(default="", alias="wbSize")


class WBCard(_RawBase):
    """A product card: nmID identity, seller vendor code, title, and sizes."""

    nm_id: int = Field(alias="nmID")
    vendor_code: str = Field(default="", alias="vendorCode")
    title: str = Field(default="", alias="title")
    sizes: list[WBCardSize] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Advertising Full Stats — GET /adv/v3/fullstats
# --------------------------------------------------------------------------- #
class WBAdvNm(_RawBase):
    """Innermost ``nms`` (SKU) node inside an advertising platform bucket."""

    nm_id: int = Field(alias="nmId")
    views: int = Field(default=0)
    clicks: int = Field(default=0)
    atbs: int = Field(default=0)  # add-to-basket (add-to-cart) count
    sum: float = Field(default=0.0)
    orders: int = Field(default=0)
    sum_price: float = Field(default=0.0)  # ad-attributed order revenue (₽)


class WBAdvApp(_RawBase):
    """A platform bucket (``apps``) grouping SKU stats by ``appType``."""

    app_type: int = Field(alias="appType")
    nms: list[WBAdvNm] = Field(default_factory=list)


class WBAdvDay(_RawBase):
    """A single calendar day of advertising stats for one campaign."""

    stat_date: date = Field(alias="date")
    apps: list[WBAdvApp] = Field(default_factory=list)


class WBAdvCampaignStats(_RawBase):
    """Top-level advertising fullstats record for one campaign id."""

    campaign_id: int = Field(alias="advertId")
    days: list[WBAdvDay] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Stocks Report — POST /api/analytics/v1/stocks-report/wb-warehouses
# --------------------------------------------------------------------------- #
class WBStockRow(_RawBase):
    """A per-size/per-warehouse stock quantity snapshot for one SKU.

    WB returns one row per ``(nmId, chrtId, warehouse)`` — ``chrtId`` is the
    size characteristic id. There is no human-readable size label on this
    endpoint (would require the content-cards API).
    """

    nm_id: int = Field(alias="nmId")
    chrt_id: int = Field(alias="chrtId")
    warehouse_name: str = Field(alias="warehouseName")
    region_name: str = Field(default="", alias="regionName")
    quantity: int = Field(default=0, alias="quantity")
    in_way_to_client: int = Field(default=0, alias="inWayToClient")
    in_way_from_client: int = Field(default=0, alias="inWayFromClient")


# --------------------------------------------------------------------------- #
# Campaign list — GET /adv/v1/promotion/count
# Response: {"adverts": [{"type": .., "status": .., "count": ..,
#                         "advert_list": [{"advertId": .., "changeTime": ..}]}]}
# --------------------------------------------------------------------------- #
class WBAdvertRef(_RawBase):
    """A single campaign reference inside a promotion-count group."""

    advert_id: int = Field(alias="advertId")


class WBCampaignGroup(_RawBase):
    """A ``type`` + ``status`` group listing its campaign ids."""

    type: int = Field(alias="type")
    status: int = Field(alias="status")
    advert_list: list[WBAdvertRef] = Field(default_factory=list, alias="advert_list")


class WBCampaign(_RawBase):
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
class WBAdvertPlacements(_RawBase):
    """Display-zone toggles of a campaign (search / recommendations)."""

    search: bool = False
    recommendations: bool = False


class WBAdvertSettings(_RawBase):
    """The ``settings`` block of an advert: name, payment model, placements."""

    name: str = ""
    payment_type: str = ""
    placements: WBAdvertPlacements = Field(default_factory=WBAdvertPlacements)


class WBAdvertNmSetting(_RawBase):
    """A per-SKU settings node of an advert (only the identity is consumed)."""

    nm_id: int


class WBAdvertV2(_RawBase):
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
class WBNormQueryStat(_RawBase):
    """Metrics of one search cluster on one day (search zone only)."""

    views: int = Field(default=0)
    clicks: int = Field(default=0)
    atbs: int = Field(default=0)
    orders: int = Field(default=0)
    spend: float = Field(default=0.0)


class WBNormQueryDaily(_RawBase):
    """One ``dailyStats`` entry: a calendar day of one search cluster."""

    stat_date: date = Field(alias="date")
    stat: WBNormQueryStat = Field(default_factory=WBNormQueryStat)


class WBNormQueryItem(_RawBase):
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
