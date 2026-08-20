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

from src.modules.ab_tests.models import AbTest, AbTestVariant, VariantStatDaily
from src.modules.ab_tests.schemas import VariantMetrics
from src.modules.ab_tests.services.metrics import DayCounts, conversions, totals_from_days


def _day_counts(row: VariantStatDaily) -> DayCounts:
    """Convert a persisted day into the arithmetic's input type."""
    return DayCounts(
        stat_date=row.stat_date,
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
    days: Iterable[VariantStatDaily],
    image_url: str,
) -> list[VariantMetrics]:
    """Build the per-photo result rows for one test.

    Args:
        test: The test being rendered (supplies the live variant).
        variants: Its photos, in rotation order.
        days: Every attributed day of the test, any order.
        image_url: A ``str.format`` template taking ``test_id`` and
            ``variant_id`` — the route the SPA fetches the picture from.

    Returns:
        One row per variant, in rotation order. A photo that has never been
        live still gets a row, with zero counts and ``None`` ratios, so the
        table shows what is queued as well as what has run.
    """
    by_variant: dict[uuid.UUID, list[DayCounts]] = {variant.id: [] for variant in variants}
    for row in days:
        if row.variant_id in by_variant:
            by_variant[row.variant_id].append(_day_counts(row))

    rows: list[VariantMetrics] = []
    for variant in variants:
        variant_days = by_variant[variant.id]
        totals = totals_from_days(variant_days)
        ratios = conversions(totals)
        rows.append(
            VariantMetrics(
                variant_id=variant.id,
                position=variant.position,
                image_url=image_url.format(test_id=test.id, variant_id=variant.id),
                is_active=test.active_variant_id == variant.id,
                click_through=ratios.click_through,
                add_to_cart=ratios.add_to_cart,
                order_rate=ratios.order_rate,
                views=totals.views,
                clicks=totals.clicks,
                atbs=totals.atbs,
                orders=totals.orders,
                spend=totals.spend,
                days_measured=len(variant_days),
            )
        )
    return rows


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
