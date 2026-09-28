"""Raw payload models for the WB Seller Analytics surface (funnel + stocks).

These Pydantic models mirror the *nested* shape WB returns on the wire. The
Monitoring module's ingestion service flattens these trees into the clean
relational records defined by its own ORM models — the raw shapes never leak
past the integration boundary.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase

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


class WBFunnelHistoryDay(RawBase):
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


class WBFunnelHistoryProduct(RawBase):
    """The ``product`` identity block of a funnel node (history and aggregate).

    ``feedback_rating`` is the card's buyer rating — the storefront's stars —
    served by the period aggregate (``sales-funnel/products``); it matched the
    storefront's ``reviewRating`` on every card checked (2026-09-26). ``0`` is
    WB's value for a card with no reviews. Not to be confused with
    ``productRating``, WB's 0-10 card-quality score, which is not read.
    """

    nm_id: int = Field(alias="nmId")
    feedback_rating: float | None = Field(default=None, alias="feedbackRating")


class WBFunnelHistoryRow(RawBase):
    """One product node holding its full per-day funnel ``history``."""

    product: WBFunnelHistoryProduct
    history: list[WBFunnelHistoryDay] = Field(default_factory=list)

    @property
    def nm_id(self) -> int:
        """SKU identifier of this product."""
        return self.product.nm_id


# --------------------------------------------------------------------------- #
# Sales Funnel — period AGGREGATE (the buyout/cancel cohort source)
# POST /api/analytics/v3/sales-funnel/products
#
# Why this endpoint exists in the pipeline alongside the daily history above:
#
#  * The daily history is the only per-day series, but it is capped at the
#    last 7 days AND serves no cancel count. A cohort's deliveries keep being
#    accepted/refused for ~3 weeks, so a day harvested through the history feed
#    freezes at <=7 days of maturity and can never be refreshed.
#  * This aggregate accepts an ARBITRARY period (verified live 2026-07-16:
#    start = today-21 returns 200 where the history feed 400s) and serves the
#    real ``cancelCount``. Called with ``start == end`` it yields one matured
#    per-day cohort.
#
# Verified live shape::
#   {"data": {"products": [
#      {"product": {"nmId": .., "title": .., ...},
#       "statistic": {"selected": {"period": {...}, "orderCount": ..,
#                                  "buyoutCount": .., "cancelCount": ..,
#                                  "conversions": {"buyoutPercent": ..}},
#                     "past": {...}, "comparison": {...}}}, ...]}}
#
# NOTE: the ``nmIDs`` body filter is IGNORED by WB — the response always carries
# the seller's whole catalogue (40 products, single page for this account). The
# caller filters client-side; do not rely on the request narrowing the result.
# --------------------------------------------------------------------------- #


class WBFunnelAggregateSelected(RawBase):
    """The ``selected`` period block of an aggregate node.

    ``buyoutPercent`` is WB's own figure and satisfies
    ``buyout_count / (buyout_count + cancel_count)`` exactly (verified live:
    567 / (567 + 965) = 37% = WB's reported 37) — the two counts ARE the
    definition of «Процент выкупа», so we store them and never round-trip
    through the percent.

    The funnel counts (``openCount``/``cartCount``/``orderCount``) mirror the
    daily history feed's fields. The nightly cohort pass ignores them, but the
    historical backfill (``scripts/backfill_history.py``) relies on them: this
    aggregate is the ONLY funnel surface serving periods older than 7 days, so
    called with ``start == end`` per day it reconstructs the full daily series.
    NB the wishlist alias differs from the daily feed's (``addToWishlist``
    here vs ``addToWishlistCount`` there) — both verified live 2026-07-16.
    """

    open_count: int = Field(default=0, alias="openCount")
    cart_count: int = Field(default=0, alias="cartCount")
    order_count: int = Field(default=0, alias="orderCount")
    buyout_count: int = Field(default=0, alias="buyoutCount")
    cancel_count: int = Field(default=0, alias="cancelCount")
    add_to_wishlist: int = Field(default=0, alias="addToWishlist")

    @property
    def has_activity(self) -> bool:
        """Whether the period saw any funnel event at all."""
        return bool(
            self.open_count
            or self.cart_count
            or self.order_count
            or self.buyout_count
            or self.cancel_count
            or self.add_to_wishlist
        )


class WBFunnelAggregateStatistic(RawBase):
    """The ``statistic`` block; only ``selected`` (our requested period) is used."""

    selected: WBFunnelAggregateSelected


class WBFunnelAggregateRow(RawBase):
    """One product node of the period-aggregate response."""

    product: WBFunnelHistoryProduct
    statistic: WBFunnelAggregateStatistic

    @property
    def nm_id(self) -> int:
        """SKU identifier of this product."""
        return self.product.nm_id


# --------------------------------------------------------------------------- #
# Stocks Report — POST /api/analytics/v1/stocks-report/wb-warehouses
# --------------------------------------------------------------------------- #


class WBStockRow(RawBase):
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
