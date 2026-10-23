"""Cluster search response DTOs — scoped to ONE SKU.

The feature lives at the bottom of a SKU's monitoring page:
:class:`SkuClustersResponse` is the search clusters this SKU's ads served in
over the page's window — stored history from ``POST /adv/v1/normquery/stats``,
covering only phrases the seller paid to appear for.

A cluster window is a window of PAID impressions and is never an organic rank.
The live-position DTOs that used to share this module went with the feature on
2026-08-27 — see ``docs/monitoring/LIVE_POSITION.md``.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from src.modules.monitoring.schemas.summary import MetricWindow


class ClusterDayStat(BaseModel):
    """One day of a cluster's window (the trend behind a row)."""

    stat_date: date
    views: int
    clicks: int
    orders: int
    spend: float


class SkuClusterItem(BaseModel):
    """One search cluster's advertising totals for this SKU over the window.

    ``avg_position`` is the impression-weighted average AD position inside the
    cluster and is ``None`` when WB reported no position — which is not the same
    as ranking last, so it must never render as 0.

    The money is in what the cluster's campaigns' spend is stored in — the
    workspace's currency, rouble campaigns converted at the Bank rate of their day.
    A campaign the conversion could not reach (a day past the loaded rates)
    would add roubles to soms, so ``spend``/``cpc``/``cpm`` are ``None`` there.
    """

    cluster: str = Field(description="Normalized search phrase WB grouped queries under.")
    views: int
    clicks: int
    add_to_cart: int = Field(description="Add-to-cart events (WB `atbs`).")
    orders: int
    spend: float | None = Field(
        description="In ``currencies``; None when its campaigns bill in two currencies."
    )
    ctr: float = Field(description="clicks / views * 100 (%).")
    cpc: float | None = Field(description="spend / clicks, in ``currencies``.")
    cpm: float | None = Field(description="spend / views * 1000, in ``currencies``.")
    currencies: list[str] = Field(
        default_factory=list,
        description="What the cluster's campaigns bill in; empty when none states it.",
    )
    avg_position: float | None = Field(
        default=None, description="Impression-weighted average ad position; None = unreported."
    )
    days_count: int = Field(description="Days in the window with impressions.")
    campaign_count: int = Field(description="Distinct campaigns that served the cluster.")
    daily: list[ClusterDayStat] = Field(
        default_factory=list,
        description="Per-day totals; every day of the window, zero-filled where WB reported none.",
    )


class SkuClustersResponse(BaseModel):
    """The SKU's search clusters over the window, most impressions first."""

    nm_id: int
    window: MetricWindow
    items: list[SkuClusterItem] = Field(default_factory=list)
