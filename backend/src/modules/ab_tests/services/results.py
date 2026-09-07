"""Assembling the result table: one row per photo, columns are the metrics.

Deliberately laid out the opposite way round to WB's own A/B screen. WB compares
exactly two images, so it can afford variants as *columns* and metrics as rows;
a rotation runs up to ten, so photos become the rows and the metrics the
columns — otherwise the table grows sideways off the page.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal

from src.modules.ab_tests.models import AbTest, AbTestVariant, VariantStatWindow
from src.modules.ab_tests.schemas import VariantMetrics
from src.modules.ab_tests.services.metrics import (
    WindowCounts,
    conversions,
    totals_from_windows,
)


def _window_counts(row: VariantStatWindow) -> WindowCounts:
    """Convert a persisted interval into the arithmetic's input type."""
    return WindowCounts(
        window_end=row.window_end,
        views=row.views,
        clicks=row.clicks,
        atbs=row.atbs,
        orders=row.orders,
        spend=Decimal(row.spend),
    )


def build_rows(
    *,
    test: AbTest,
    variants: Sequence[AbTestVariant],
    windows: Iterable[VariantStatWindow],
    image_url: str,
) -> list[VariantMetrics]:
    """Build the per-photo result rows for one test.

    Args:
        test: The test being rendered (supplies the live variant).
        variants: Its photos, in rotation order.
        windows: Every recorded polling interval of the test, any order.
        image_url: A ``str.format`` template taking ``test_id`` and
            ``variant_id`` — the route the SPA fetches the picture from.

    Returns:
        One row per variant, in rotation order — which puts the card's own
        photo first, since it holds position 0. A photo that has never been
        live still gets a row, with zero counts and ``None`` ratios, so the
        table shows what is queued as well as what has run.
    """
    by_variant: dict[uuid.UUID, list[WindowCounts]] = {variant.id: [] for variant in variants}
    for row in windows:
        if row.variant_id in by_variant:
            by_variant[row.variant_id].append(_window_counts(row))

    rows: list[VariantMetrics] = []
    for variant in variants:
        variant_windows = by_variant[variant.id]
        totals = totals_from_windows(variant_windows)
        ratios = conversions(totals)
        rows.append(
            VariantMetrics(
                variant_id=variant.id,
                position=variant.position,
                image_url=image_url.format(test_id=test.id, variant_id=variant.id),
                is_active=test.active_variant_id == variant.id,
                is_original=variant.is_original,
                click_through=ratios.click_through,
                add_to_cart=ratios.add_to_cart,
                order_rate=ratios.order_rate,
                views=totals.views,
                clicks=totals.clicks,
                atbs=totals.atbs,
                orders=totals.orders,
                spend=totals.spend,
                days_measured=_days_spanned(variant_windows),
            )
        )
    return rows


def _days_spanned(windows: Sequence[WindowCounts]) -> int:
    """How many distinct calendar days a variant's intervals touched.

    Reported instead of a raw interval count because "27 windows" means nothing
    to a reader while "2 days" does, and because the poll interval is a
    deployment setting rather than a property of the test.

    Args:
        windows: The variant's recorded intervals.

    Returns:
        The number of distinct days.
    """
    return len({window.window_end.date() for window in windows})


def leader_of(rows: Sequence[VariantMetrics]) -> uuid.UUID | None:
    """Return the photo with the best click-through, if one can be named.

    Only rows with a measured ratio compete: a variant that has not been live
    has no CTR, and treating its absence as 0 % would let any measured photo
    "beat" it without evidence.

    Args:
        rows: The test's result rows.

    Returns:
        The winning variant id, or ``None`` when nothing has been measured.
    """
    measured = [row for row in rows if row.click_through is not None]
    if not measured:
        return None
    return max(measured, key=lambda row: (row.click_through or Decimal(0), row.views)).variant_id
