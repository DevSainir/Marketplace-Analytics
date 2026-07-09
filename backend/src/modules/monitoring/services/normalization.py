"""Pure data-cleansing math for "Baseline Organic Demand".

Implements the MVP normalization sequence from ``api_contracts.md`` §5:

1. **OOS masking** — exclude calendar days where the SKU's total stock hit 0
   (do not count them as zero demand).
2. **Promotional lift filtering** — ``cleaned = raw / promo_lift_factor``.
3. **Category seasonality adjustment** —
   ``baseline = promo_cleaned / seasonality_index``.

Every function here is pure (no I/O, no DB, no mutation of inputs) so the logic
is trivially unit-testable and reusable by both the API and worker paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DailyDemandPoint:
    """One day's raw demand plus the factors needed to cleanse it.

    Attributes:
        day: The calendar day (Moscow time).
        raw_orders: Raw order count for the day.
        total_stock: Total remaining stock across all warehouses that day.
        promo_lift_factor: Multiplier capturing promo-driven uplift
            (``1.0`` == no active promotion).
        seasonality_index: Category seasonality coefficient
            (``1.0`` == neutral season).
    """

    day: date
    raw_orders: int
    total_stock: int
    promo_lift_factor: float = 1.0
    seasonality_index: float = 1.0


@dataclass(frozen=True, slots=True)
class BaselineDemandResult:
    """Outcome of the normalization pipeline for a set of daily points.

    Attributes:
        baseline_organic_demand: Mean cleansed daily demand over in-stock days.
        oos_days_excluded: Count of days masked out as out-of-stock.
        considered_days: Count of days that contributed to the average.
    """

    baseline_organic_demand: float
    oos_days_excluded: int
    considered_days: int


def _is_out_of_stock(point: DailyDemandPoint) -> bool:
    """Return ``True`` when the SKU had zero total stock on this day."""
    return point.total_stock <= 0


def _cleanse_day(point: DailyDemandPoint) -> float:
    """Apply promo-lift and seasonality cleansing to a single in-stock day.

    Guards against division by zero by treating a non-positive factor as the
    neutral value ``1.0``.

    Args:
        point: The day to cleanse (assumed in-stock).

    Returns:
        The cleansed organic demand for that day.
    """
    promo_factor = point.promo_lift_factor if point.promo_lift_factor > 0 else 1.0
    seasonality = point.seasonality_index if point.seasonality_index > 0 else 1.0
    promo_cleaned = point.raw_orders / promo_factor
    return promo_cleaned / seasonality


def compute_baseline_demand(
    points: list[DailyDemandPoint],
) -> BaselineDemandResult:
    """Compute baseline organic demand from daily points.

    Steps: mask OOS days, cleanse remaining days for promo lift and
    seasonality, then average across the surviving in-stock days.

    Args:
        points: The per-day demand points for a single SKU.

    Returns:
        A :class:`BaselineDemandResult`. When every day is OOS (or the input is
        empty) the baseline is ``0.0`` and ``considered_days`` is ``0``.
    """
    in_stock = [p for p in points if not _is_out_of_stock(p)]
    oos_excluded = len(points) - len(in_stock)

    if not in_stock:
        return BaselineDemandResult(
            baseline_organic_demand=0.0,
            oos_days_excluded=oos_excluded,
            considered_days=0,
        )

    cleansed_total = sum(_cleanse_day(p) for p in in_stock)
    baseline = cleansed_total / len(in_stock)
    return BaselineDemandResult(
        baseline_organic_demand=round(baseline, 4),
        oos_days_excluded=oos_excluded,
        considered_days=len(in_stock),
    )
