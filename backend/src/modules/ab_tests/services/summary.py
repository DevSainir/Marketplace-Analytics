"""The one-line answer to «что вообще насчитал этот тест».

The result table compares photos against each other; this compares the test
against itself. It exists because every figure on the page is a *share* of
something the page never states — a variant's 4 000 показов mean one thing when
the test has counted 8 000 and another when it has counted 400 000 — and because
the two questions a seller asks before believing any of it («сколько уже
собрано» and «за сколько времени») had no answer anywhere in the payload.

**Everything here is summed from the same rows the table divides.** Not from
WB, not from a second query, not from a stored counter: the identical
:class:`~..models.stats.VariantStatWindow` list that
:func:`..services.results.build_rows` walks. That is the property that makes the
block checkable rather than decorative — the total показов is the sum of the
table's «Показов» line, to the impression, always, and a reader who adds the
columns up and gets the same number has verified the page rather than trusted
it.

Two clocks, and they are deliberately not the same number:

* **Измерено** — the length of the union of the intervals that carry the
  counts. This is the exposure the CTR is divided over; it is what «за
  столько-то» honestly means. A union, not a sum: every interval is stored once
  per advertising campaign, so with two campaigns serving the same hour that
  hour has two rows, and summing them reported a 20-hour test as «1 д 17 ч».
* **Прошло** — wall clock from the first install to the finish (or to now).

They differ by every stretch the test was not accruing: a hand pause, a campaign
that stopped serving, a poll that read nothing. The gap is reported rather than
hidden, because a test that ran «14 часов» while measuring four of them is a
test whose numbers are thin for a reason the seller can act on — switch the
advertising back on — and averaging the difference away would present the same
1 200 показов as if they were a day's worth.

The wall clock itself is NOT computed here: it ends at «сейчас» for a live test,
and a duration frozen at the last poll would be wrong on the screen within
seconds. The client ticks it from ``started_at``/``finished_at``, the same way
the rotation countdown ticks — see ``TestSummary.vue``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime

from src.modules.ab_tests.models import AbTestVariant, VariantStatWindow
from src.modules.ab_tests.schemas import AbTestSummary
from src.modules.ab_tests.services.metrics import conversions, totals_from_windows
from src.modules.ab_tests.services.results import window_counts


def build_summary(
    *,
    variants: Sequence[AbTestVariant],
    windows: Iterable[VariantStatWindow],
    rounds_completed: int,
) -> AbTestSummary:
    """Total what a test has measured, over every photo and every turn.

    Args:
        variants: Its photos, in rotation order — the same sequence the result
            table is built from, so «варианта из» counts what is on screen.
        windows: Every recorded polling interval of the test, any order.
        rounds_completed: Laps the rotation has served, as the detail computes
            it. Passed in rather than re-derived so the block and the round
            filter above the table can never name a different number.

    Returns:
        The summary payload.
    """
    # Only windows belonging to a photo still on the test are counted, because
    # that is the set the result table sums. The two are equal today — a deleted
    # variant cascades its windows away — and keeping the filter means they stay
    # equal if that ever stops being true, rather than the block quietly
    # exceeding the table by an orphan's traffic.
    known = {variant.id for variant in variants}
    counted = [row for row in windows if row.variant_id in known]

    totals = totals_from_windows([window_counts(row) for row in counted])
    ratios = conversions(totals)

    measured_seconds = _covered_seconds((row.window_start, row.window_end) for row in counted)

    earned: set[uuid.UUID] = {row.variant_id for row in counted if row.views}

    return AbTestSummary(
        views=totals.views,
        clicks=totals.clicks,
        atbs=totals.atbs,
        orders=totals.orders,
        spend=totals.spend,
        click_through=ratios.click_through,
        add_to_cart=ratios.add_to_cart,
        order_rate=ratios.order_rate,
        measured_minutes=int(measured_seconds // 60),
        windows=len(counted),
        first_window_at=min((row.window_start for row in counted), default=None),
        last_window_at=max((row.window_end for row in counted), default=None),
        rounds_completed=rounds_completed,
        variants_measured=len(earned),
        variants_total=len(variants),
    )


def _covered_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    """Length of the union of `intervals` — time covered, each moment once.

    Rows of different campaigns share one polling interval exactly, and rows of
    consecutive polls touch end to start; merging handles both, and any partial
    overlap besides.
    """
    total = 0.0
    run_start: datetime | None = None
    run_end: datetime | None = None
    for start, end in sorted(intervals):
        if run_end is None or start > run_end:
            if run_start is not None and run_end is not None:
                total += (run_end - run_start).total_seconds()
            run_start, run_end = start, end
        elif end > run_end:
            run_end = end
    if run_start is not None and run_end is not None:
        total += (run_end - run_start).total_seconds()
    return total


__all__ = ["build_summary"]
