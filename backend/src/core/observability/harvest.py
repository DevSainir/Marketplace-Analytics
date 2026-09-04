"""Recording what a harvest actually did, not merely that it ran.

The distinction this module exists for is one this codebase has already paid
for. After the Redis pool leak, every ``harvest_sku_window`` after a worker's
first task lost its ``sales-funnel`` source and kept reporting **success** with
``funnel_rows: 0`` — for days, while «Обновить» users watched unchanged numbers
and concluded the button did nothing
(:func:`src.core.tasks.run_task` carries the full account).

Nothing about that was visible in a task-level metric. The task succeeded. It
was visible in exactly two numbers that nothing was recording: rows written per
source, and sources that failed. So those are what this records, and they are
recorded from :class:`HarvestOutcome` — the structure the harvest code already
builds for the same reason, rather than a second description of the run that
could disagree with the first.

A partial harvest is a **success with a failure counted inside it**. That is
the shape the domain actually has: a failed WB source must not lose the rest of
the run, which is a deliberate tolerance and therefore precisely the thing that
needs its own counter — without one, tolerance and absence of a problem look
identical.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager

from src.core.observability.metrics import HARVEST_DURATION, HARVEST_PARTIAL, HARVEST_ROWS

#: Suffix the harvest code puts on every count key (``funnel_rows``,
#: ``stock_rows``). Stripped so the metric label is the source itself, which is
#: what a dashboard legend should read and what ``failed_sources`` already
#: names its entries.
_COUNT_SUFFIX = "_rows"


def _source_label(key: str) -> str:
    """Turn a count key into the source it counts."""
    return key.removesuffix(_COUNT_SUFFIX)


def record_harvest_outcome(
    harvest: str,
    *,
    counts: Mapping[str, object],
    failed_sources: Iterable[str] = (),
) -> None:
    """Record one harvest's rows and any sources that withheld data.

    Args:
        harvest: The harvest's name, e.g. ``monitoring.sku_window``. A closed
            set — one value per task, chosen at the call site rather than
            derived from an argument, so no input can invent a label.
        counts: Rows persisted per metric family, as
            :class:`HarvestOutcome.counts` holds them. Non-integer values are
            skipped rather than coerced: the same mapping carries
            ``failed_sources`` in some call sites' return values, and counting
            a list as rows would be worse than counting nothing.
        failed_sources: Sources WB did not answer for.
    """
    for key, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        # Incremented even by zero. A counter that is never touched is absent
        # from the exposition entirely, and `rate()` over an absent series is
        # not zero — it is nothing, which a graph draws as a gap and an alert
        # reads as "no data" rather than "no rows". Touching it makes the flat
        # line exist, and a flat line at zero IS the alert.
        HARVEST_ROWS.labels(harvest=harvest, source=_source_label(key)).inc(value)
    for source in failed_sources:
        HARVEST_PARTIAL.labels(harvest=harvest, source=source).inc()


@contextmanager
def harvest_timer(harvest: str) -> Iterator[None]:
    """Time a harvest and record its outcome bucket.

    Args:
        harvest: The harvest's name.

    Yields:
        Nothing; the block's body is the harvest.

    The ``outcome`` label separates ``ok`` from ``error``, and the error case
    is recorded on the way out of an exception rather than skipped — a harvest
    that raised still took time, and how long it took before failing is how you
    tell a fast refusal (a rotated token) from a slow one (WB stalling the
    connection until a read timeout).
    """
    started = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        HARVEST_DURATION.labels(harvest=harvest, outcome=outcome).observe(
            time.perf_counter() - started
        )


__all__ = ["harvest_timer", "record_harvest_outcome"]
