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

from src.modules.ab_tests.models import (
    AbTest,
    AbTestVariant,
    VariantExposure,
    VariantStatWindow,
)
from src.modules.ab_tests.schemas import ExposureRow, VariantMetrics
from src.modules.ab_tests.services.metrics import (
    WindowCounts,
    conversions,
    totals_from_windows,
)
from src.modules.ab_tests.services.rounds import gap_to_best, standings


def window_counts(row: VariantStatWindow) -> WindowCounts:
    """Convert a persisted interval into the arithmetic's input type.

    Public because the test-level summary in :mod:`.summary` sums the identical
    rows this module divides, and it has to do it through the same conversion —
    a second one is how a total stops matching the column it totals.
    """
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
    exposures: Sequence[VariantExposure] = (),
    image_url: str,
) -> list[VariantMetrics]:
    """Build the per-photo result rows for one test.

    Args:
        test: The test being rendered (supplies the live variant).
        variants: Its photos, in rotation order.
        windows: Every recorded polling interval of the test, any order.
        exposures: The test's turns, which carry the lap each window belongs to.
            Empty is allowed and yields zeroed round columns — a test that has
            never been polled has no laps to stand in.
        image_url: A ``str.format`` template taking ``test_id`` and
            ``variant_id`` — the route the SPA fetches the picture from.

    Returns:
        One row per variant, in rotation order — which puts the card's own
        photo first, since it holds position 0. A photo that has never been
        live still gets a row, with zero counts and ``None`` ratios, so the
        table shows what is queued as well as what has run.
    """
    # Materialised because it is walked twice — once into per-variant counts and
    # once into per-lap standings — and the caller may hand us a generator.
    windows_by_variant = list(windows)
    by_variant: dict[uuid.UUID, list[WindowCounts]] = {variant.id: [] for variant in variants}
    for row in windows_by_variant:
        if row.variant_id in by_variant:
            by_variant[row.variant_id].append(window_counts(row))

    laps = standings(
        variant_ids=[variant.id for variant in variants],
        windows=list(windows_by_variant),
        exposures=exposures,
    )

    # The bar every other photo is measured against. Computed over the whole
    # test rather than per row so the «-51 %» column means the same thing in
    # every row of one table.
    measured = [conversions(totals_from_windows(by_variant[v.id])).click_through for v in variants]
    best = max((ctr for ctr in measured if ctr is not None), default=None)

    rows: list[VariantMetrics] = []
    for variant in variants:
        variant_windows = by_variant[variant.id]
        totals = totals_from_windows(variant_windows)
        ratios = conversions(totals)
        standing = laps[variant.id]
        ctr_gap, ctr_result = gap_to_best(ratios.click_through, best)
        rows.append(
            VariantMetrics(
                variant_id=variant.id,
                position=variant.position,
                image_url=image_url.format(test_id=test.id, variant_id=variant.id),
                is_active=test.active_variant_id == variant.id,
                is_original=variant.is_original,
                is_excluded=variant.is_excluded,
                rounds_played=standing.rounds_played,
                rounds_won=standing.rounds_won,
                ctr_gap=ctr_gap,
                ctr_result=ctr_result,
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


def build_history(
    *,
    test: AbTest,
    variants: Sequence[AbTestVariant],
    windows: Iterable[VariantStatWindow],
    exposures: Sequence[VariantExposure],
    image_url: str,
) -> list[ExposureRow]:
    """One row per turn the rotation has served, newest first.

    The result table answers «which photo is best»; this answers «what actually
    happened», and the second question is the one asked when the first answer
    looks wrong. A turn that ran nine minutes instead of thirty, or a photo that
    came up twice in a lap, is invisible in the totals and obvious here.

    Traffic is attributed to a turn the same way the rotation attributes it: a
    window belongs to whichever exposure was open when it closed.

    Args:
        test: The test being rendered.
        variants: Its photos, for the label and the picture.
        windows: Every recorded interval of the test.
        exposures: The turns, newest first.
        image_url: ``str.format`` template for the picture route.

    Returns:
        One row per exposure, in the order given.
    """
    by_id = {variant.id: variant for variant in variants}
    rows: list[ExposureRow] = []

    for exposure in exposures:
        variant = by_id.get(exposure.variant_id)
        if variant is None:  # pragma: no cover - the FK cascades
            continue

        views = clicks = 0
        for window in windows:
            if window.variant_id != exposure.variant_id:
                continue
            if window.window_end < exposure.activated_at:
                continue
            if exposure.deactivated_at is not None and window.window_end > exposure.deactivated_at:
                continue
            views += window.views
            clicks += window.clicks

        # A live turn is measured up to now by the reader's own clock; storing a
        # duration here would freeze at whatever the last poll happened to be.
        end = exposure.deactivated_at
        minutes = (
            int((end - exposure.activated_at).total_seconds() // 60) if end is not None else None
        )

        rows.append(
            ExposureRow(
                variant_id=variant.id,
                position=variant.position,
                is_original=variant.is_original,
                image_url=image_url.format(test_id=test.id, variant_id=variant.id),
                round_number=exposure.round_number,
                activated_at=exposure.activated_at,
                deactivated_at=exposure.deactivated_at,
                minutes=minutes,
                views=views,
                clicks=clicks,
                click_through=conversions(
                    totals_from_windows(
                        [
                            WindowCounts(
                                window_end=exposure.activated_at,
                                views=views,
                                clicks=clicks,
                                atbs=0,
                                orders=0,
                                spend=Decimal(0),
                            )
                        ]
                    )
                ).click_through,
            )
        )
    return rows
