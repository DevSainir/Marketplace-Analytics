"""Advertising-stats response DTOs (campaign-grouped view)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AdMetrics(BaseModel):
    """Derived advertising efficiency metrics (computed, not stored)."""

    cpm: float = Field(description="Cost per mille — spend / views * 1000 (rubles).")
    ctr: float = Field(description="Click-through rate — clicks / views * 100 (%).")
    cpc: float = Field(description="Cost per click — spend / clicks (rubles).")
    cart_conversion: float = Field(description="Click -> cart — add_to_cart / clicks * 100 (%).")
    order_conversion: float = Field(description="Cart -> order — orders / add_to_cart * 100 (%).")


def compute_ad_metrics(
    *, views: int, clicks: int, add_to_cart: int, spend: float, orders: int
) -> AdMetrics:
    """Compute CPM / CTR / CPC and cart/order conversions (zero-safe)."""
    return AdMetrics(
        cpm=round(spend / views * 1000, 2) if views else 0.0,
        ctr=round(clicks / views * 100, 2) if views else 0.0,
        cpc=round(spend / clicks, 2) if clicks else 0.0,
        cart_conversion=round(add_to_cart / clicks * 100, 2) if clicks else 0.0,
        order_conversion=round(orders / add_to_cart * 100, 2) if add_to_cart else 0.0,
    )


class CampaignDailyStat(BaseModel):
    """One day/platform advertising row within a single campaign."""

    stat_date: date
    app_type: int
    views: int
    clicks: int
    add_to_cart: int = Field(description="Add-to-cart events (WB `atbs`).")
    spend: float
    orders: int
    metrics: AdMetrics = Field(description="Derived CPM/CTR/CPC for this row.")


class CampaignAdvertising(BaseModel):
    """A SKU's advertising for one campaign: totals plus a daily breakdown.

    ``type``/``status``/``status_label``/``type_label`` come from the campaigns
    dimension and are ``None`` when the campaign has not been synced yet.
    """

    campaign_id: int
    type: int | None = Field(default=None, description="WB campaign type code.")
    type_label: str | None = Field(
        default=None, description="Human-readable type (auction/auto/search/...)."
    )
    status: int | None = Field(default=None, description="Raw WB status code.")
    status_label: str | None = Field(
        default=None, description="Normalized status (active/paused/completed/...)."
    )
    views: int = Field(description="Campaign total views over the window.")
    clicks: int = Field(description="Campaign total clicks over the window.")
    add_to_cart: int = Field(description="Campaign total add-to-cart events.")
    spend: float = Field(description="Campaign total spend over the window.")
    orders: int = Field(
        description="Campaign total orders for THIS SKU over the window "
        "(a campaign's own total across all its SKUs will be higher)."
    )
    metrics: AdMetrics = Field(description="Derived CPM/CTR/CPC for the campaign.")
    daily: list[CampaignDailyStat] = Field(
        default_factory=list, description="Per-day/platform breakdown."
    )
