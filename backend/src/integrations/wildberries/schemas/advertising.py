"""Raw payload models for the WB Advertising surface.

Covers campaign full stats, the campaign listings (promotion/count and the v2
adverts descriptor), the search-cluster (normquery) statistics used to split
unified-bid campaigns by display zone, and the write-off ledger that names how
each advertising charge was funded.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

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
    sum_price: float = Field(default=0.0)  # ad-attributed order revenue, campaign currency


class WBAdvApp(RawBase):
    """A platform bucket (``apps``) grouping SKU stats by ``appType``."""

    app_type: int = Field(alias="appType")
    nms: list[WBAdvNm] = Field(default_factory=list)


class WBAdvDay(RawBase):
    """A single calendar day of advertising stats for one campaign."""

    stat_date: date = Field(alias="date")
    apps: list[WBAdvApp] = Field(default_factory=list)


class WBAdvCampaignStats(RawBase):
    """Top-level advertising fullstats record for one campaign id.

    ``currency`` is the unit of every ``sum``/``sum_price``/``cpc`` under it,
    and it is the CAMPAIGN's: fixed when the campaign was created, so campaigns
    from before WB moved the ad account to KGS on 2026-08-20 still answer RUB
    (verified live 2026-09-29 on every workspace). ``""`` if WB omits it.
    """

    campaign_id: int = Field(alias="advertId")
    currency: str = Field(default="")
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
# "timestamps": {...}}]}. ``bid_type`` is ``"unified"`` (unified bid, always
# both placements) or ``"manual"`` (manual bid, per-placement toggles).
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
# analytics layer split unified-bid campaigns: shelves = fullstats - search.
# --------------------------------------------------------------------------- #


class WBNormQueryStat(RawBase):
    """Metrics of one search cluster on one day (search zone only).

    ``norm_query`` is the cluster's own text — the normalized search phrase WB
    grouped the queries under. It is what «Поиск по кластерам» searches, so it
    is kept even though the zone-split aggregate sums clusters away. WB has been
    observed to omit it on aggregate-looking rows; those default to ``""`` and
    are dropped by the cluster ingest rather than persisted under a blank key.
    """

    norm_query: str = Field(default="", alias="normQuery")
    #: Average ad position within the cluster's search results (WB ``avgPos``);
    #: 0 when WB omits it, which reads as "unknown", not "first place".
    avg_position: float = Field(default=0.0, alias="avgPos")
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


# --------------------------------------------------------------------------- #
# Advertising write-offs — GET /adv/v1/upd
# --------------------------------------------------------------------------- #
# The ONLY WB surface that names how an advertising charge was funded. Verified
# live 2026-09-15 on one workspace: one row per write-off, carrying
# `paymentType` («Баланс» — the seller's own money — or «Кэшбэк», which WB pays
# out of the bonus pool `/adv/v1/balance` reports under `cashbacks`).
#
# Two fields of this payload are traps, and both have already produced a wrong
# number once:
#
# * `updNum` is **0 on every cashback row** (it is an invoice-document number,
#   and a bonus write-off has no invoice). Deduplicating on it collapses a
#   month of cashback into a single row — measured: a month of cashback read
#   as one write-off.
# * `currency` VARIES INSIDE ONE WINDOW. August-September 2026 returned 96
#   «Баланс» rows in RUB against 223 in KGS on the same account. Summing
#   `updSum` without splitting by currency adds unlike units.
#
# Both are why the ingested grain keeps `currency` in the primary key and never
# uses `updNum` for anything.


class WBAdvWriteOff(RawBase):
    """One advertising write-off: when, how much, for which campaign, funded how.

    Attributes:
        upd_time: Timestamp WB charged it (NOT the day the ads ran — write-offs
            are batched, so this only aligns with fullstats over a window).
        upd_sum: Amount charged, in :attr:`currency`.
        campaign_id: The campaign charged (``advertId``). There is no ``nmId``
            on this feed at all — a write-off belongs to a campaign, never to a
            SKU.
        payment_type: WB's funding-source label, verbatim.
        currency: Settlement currency of THIS row. See the module note.
    """

    upd_time: datetime = Field(alias="updTime")
    upd_sum: Decimal = Field(alias="updSum", default=Decimal(0))
    campaign_id: int = Field(alias="advertId")
    payment_type: str = Field(alias="paymentType", default="")
    currency: str = Field(default="")
