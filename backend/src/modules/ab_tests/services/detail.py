"""Assembling the detail payload the SPA renders.

Its own module because it is the one place that knows the *shape of the page*
rather than the shape of a record: the per-photo table, the log of turns, the
leader, the lap count and the clock the countdown reads all come from different
tables and are only related by being on one screen.

Keeping it out of :mod:`.catalog` keeps that service about doing things to a
test — create it, start it, exclude a photo — instead of about what a page looks
like, which is what it kept turning into every time the screen grew a column.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from src.modules.ab_tests.models import AbTest, VariantExposure, VariantStatWindow
from src.modules.ab_tests.schemas import AbTestDetail
from src.modules.ab_tests.services.results import build_history, build_rows, leader_of
from src.modules.ab_tests.services.summary import build_summary


def assemble_detail(
    *,
    test: AbTest,
    windows: Sequence[VariantStatWindow],
    exposures: Sequence[VariantExposure],
    active_since: datetime | None,
    image_url: str,
) -> AbTestDetail:
    """Build the payload for one test's page.

    Args:
        test: The test, with its variants loaded.
        windows: Every recorded polling interval of the test.
        exposures: Its turns, newest first.
        active_since: When the live photo went up — the clock the countdown on
            the page reads, and the same one the time trigger measures.
        image_url: ``str.format`` template for the picture route.

    Returns:
        The detail payload.
    """
    rows = build_rows(
        test=test,
        variants=test.variants,
        windows=windows,
        exposures=exposures,
        image_url=image_url,
    )
    rounds_completed = max((row.round_number for row in exposures), default=0)
    return AbTestDetail(
        id=test.id,
        nm_id=test.nm_id,
        vendor_code=test.vendor_code,
        name=test.name,
        status=test.status,
        trigger_mode=test.trigger_mode,
        impression_budget=test.impression_budget,
        slot_minutes=test.slot_minutes,
        active_variant_id=test.active_variant_id,
        variant_count=len(test.variants),
        started_at=test.started_at,
        finished_at=test.finished_at,
        stopped_at=test.stopped_at,
        photo_conflict_at=test.photo_conflict_at,
        created_at=test.created_at,
        leader_variant_id=leader_of(rows),
        variants=rows,
        active_since=active_since,
        history=build_history(
            test=test,
            variants=test.variants,
            windows=windows,
            exposures=exposures,
            image_url=image_url,
        ),
        rounds_completed=rounds_completed,
        summary=build_summary(
            variants=test.variants,
            windows=windows,
            rounds_completed=rounds_completed,
        ),
    )
