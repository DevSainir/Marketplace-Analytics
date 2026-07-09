"""Sales-funnel response DTOs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class _FunnelRow(Protocol):
    """Structural type for anything carrying a day's funnel counts."""

    open_count: int
    cart_count: int
    order_count: int
    buyout_count: int
    add_to_wishlist: int

    # Read-only (property) members so concrete numeric attributes — int, float,
    # or ORM Numeric/Decimal — satisfy the protocol. A plain `x: object` member
    # is mutable and therefore invariant, which no concrete type can match.
    @property
    def order_sum(self) -> object: ...
    @property
    def buyout_sum(self) -> object: ...


class FunnelDetailRead(BaseModel):
    """A single day of organic funnel metrics for one SKU."""

    model_config = ConfigDict(from_attributes=True)

    stat_date: date
    nm_id: int
    open_count: int = Field(description="Card views/opens (WB `openCount`).")
    cart_count: int
    order_count: int
    order_sum: float = Field(description="Ordered value in rubles.")
    buyout_count: int
    buyout_sum: float = Field(description="Buyout value in rubles (WB `buyoutSum`).")
    add_to_wishlist: int
    cart_conversion: float
    order_conversion: float
    buyout_conversion: float


class FunnelTotals(BaseModel):
    """Window-total organic funnel metrics for one SKU.

    Counts are **summed** across the window's days; the conversion ratios are
    **recomputed from those totals** — never summed, because WB's per-day
    conversions are whole-number percentages (summing them is meaningless).
    """

    days_count: int = Field(description="Number of days with data in the window.")
    open_count: int = Field(description="Total card opens (WB `openCount`).")
    cart_count: int = Field(description="Total add-to-cart events.")
    order_count: int = Field(description="Total orders.")
    order_sum: float = Field(description="Total ordered value in rubles.")
    buyout_count: int = Field(description="Total buyouts.")
    buyout_sum: float = Field(description="Total buyout value in rubles.")
    add_to_wishlist: int = Field(description="Total add-to-favourites events.")
    cart_conversion: float = Field(description="open -> cart: cart_count / open_count * 100 (%).")
    order_conversion: float = Field(
        description="cart -> order: order_count / cart_count * 100 (%)."
    )
    buyout_conversion: float = Field(
        description="order -> buyout: buyout_count / order_count * 100 (%)."
    )


def compute_funnel_totals(rows: Sequence[_FunnelRow]) -> FunnelTotals:
    """Roll a window's daily funnel rows up into window totals (zero-safe).

    Args:
        rows: The SKU's daily funnel rows (ORM rows or DTOs) for the window.

    Returns:
        A :class:`FunnelTotals` with summed counts and conversions recomputed
        from those totals. All zeros when ``rows`` is empty.
    """
    open_count = sum(r.open_count for r in rows)
    cart_count = sum(r.cart_count for r in rows)
    order_count = sum(r.order_count for r in rows)
    order_sum = float(sum(r.order_sum for r in rows))  # type: ignore[misc]
    buyout_count = sum(r.buyout_count for r in rows)
    buyout_sum = float(sum(r.buyout_sum for r in rows))  # type: ignore[misc]
    add_to_wishlist = sum(r.add_to_wishlist for r in rows)
    return FunnelTotals(
        days_count=len(rows),
        open_count=open_count,
        cart_count=cart_count,
        order_count=order_count,
        order_sum=order_sum,
        buyout_count=buyout_count,
        buyout_sum=buyout_sum,
        add_to_wishlist=add_to_wishlist,
        cart_conversion=round(cart_count / open_count * 100, 2) if open_count else 0.0,
        order_conversion=round(order_count / cart_count * 100, 2) if cart_count else 0.0,
        buyout_conversion=(round(buyout_count / order_count * 100, 2) if order_count else 0.0),
    )


class BaselineDemandRead(BaseModel):
    """Cleansed baseline organic demand for one SKU over a window.

    Produced by the normalization pipeline
    (:mod:`src.modules.monitoring.services.normalization`): out-of-stock days
    are masked out, the remainder cleansed for promo lift / seasonality, and
    the result averaged per in-stock day.
    """

    baseline_organic_demand: float = Field(
        description="Mean cleansed daily demand over in-stock days."
    )
    oos_days_excluded: int = Field(description="Days masked out as out-of-stock.")
    considered_days: int = Field(description="Days that contributed to the average.")


class FunnelResponseSchema(BaseModel):
    """Raw organic sales-funnel response for a single SKU.

    Exposes the per-day funnel metrics, window totals, and a raw order total.
    (The cleansed baseline lives on the detail endpoint, which has the stock
    context required for OOS masking.)
    """

    nm_id: int = Field(description="WB SKU identifier.")
    window_start: date = Field(description="Inclusive analysis window start.")
    window_end: date = Field(description="Inclusive analysis window end.")
    raw_orders: int = Field(description="Sum of raw orders across the window.")
    totals: FunnelTotals = Field(description="Window-total metrics across all days.")
    days: list[FunnelDetailRead] = Field(
        default_factory=list, description="Per-day funnel breakdown."
    )
