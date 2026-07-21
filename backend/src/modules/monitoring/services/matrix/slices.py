"""Shared value objects and numeric helpers of the matrix package.

:class:`_AdSlice` and :class:`_BucketAcc` are the package-internal currency
every matrix stage trades in: a campaign-day's advertising metrics (or a zone
slice of them) and the per-(day, bucket) accumulator such slices are folded
into. The tiny numeric helpers live here too so every stage rounds and guards
division-by-zero the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class _AdSlice:
    """Advertising metrics of one campaign-day (or a zone slice of it).

    ``order_sum`` is ``None`` when the slice's revenue cannot be attributed to
    its zone (a split campaign) — the taint propagates to the bucket.

    ``assoc_add_to_cart``/``assoc_orders`` are the campaign-level conversion
    totals INCLUDING associated size/colour variants («ассоциированные
    конверсии» — WB books a conversion on whichever variant the buyer picked,
    so only part of a campaign's carts/orders land on the advertised SKU).
    They always satisfy ``assoc_x >= x`` for a whole campaign-day slice.

    ``assoc_skus`` names the variants behind those totals (``nm_id`` →
    ``(carts, orders)``), always summing to them. ``assoc_exact`` says whether
    those per-variant counts are harvested fact or apportionment: splitting a
    campaign-day across zones divides the associated variants' counts by
    estimate (see :func:`~src.modules.monitoring.services.matrix.assoc._split_assoc_skus`),
    except where a zone took none of the extra — or all of it — and the
    division is forced.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    assoc_add_to_cart: int = 0
    assoc_orders: int = 0
    assoc_skus: dict[int, tuple[int, int]] = field(default_factory=dict)
    assoc_exact: bool = True


@dataclass
class _BucketAcc:
    """Accumulated advertising metrics of one (day, bucket) cell."""

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    assoc_add_to_cart: int = 0
    assoc_orders: int = 0
    assoc_skus: dict[int, tuple[int, int]] = field(default_factory=dict)
    assoc_exact: bool = True

    def add(self, piece: _AdSlice) -> None:
        """Fold a campaign slice into the bucket (revenue taint propagates)."""
        self.views += piece.views
        self.clicks += piece.clicks
        self.add_to_cart += piece.add_to_cart
        self.spend += piece.spend
        self.orders += piece.orders
        self.assoc_add_to_cart += piece.assoc_add_to_cart
        self.assoc_orders += piece.assoc_orders
        # One estimated slice taints the whole cell's breakdown: the listed
        # variants would no longer sum to the number the cell shows.
        self.assoc_exact = self.assoc_exact and piece.assoc_exact
        for nm_id, (carts, orders) in piece.assoc_skus.items():
            prior_carts, prior_orders = self.assoc_skus.get(nm_id, (0, 0))
            self.assoc_skus[nm_id] = (prior_carts + carts, prior_orders + orders)
        if piece.order_sum is None:
            self.order_sum = None
        elif self.order_sum is not None:
            self.order_sum += piece.order_sum


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator, or ``None`` when it cannot be computed."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 2)


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator as a percentage, or ``None`` on ÷0."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _day_range(date_from: date, date_to: date) -> list[date]:
    """Inclusive day sequence ``date_from..date_to``."""
    return [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]
