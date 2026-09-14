"""Choosing WHICH stretch of settlement history to ask WB for, and resuming it.

Separated from the walking because the two have failed independently. The walk
has died mid-page; this half has done something worse — chosen a span that
could not see the hole it was supposed to fill, and then declared the history
complete over it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from itertools import pairwise

from src.modules.workspaces.contract import LaneStep

#: How far back a new workspace's settlement history is collected.
#:
#: A product decision with a measured price, not a technical bound. WB serves
#: from the account's own beginning, so the limit is what we are willing to make
#: a new seller wait for: the endpoint answers roughly one 10 000-row page per
#: hour, and a month of settlement detail is 1 page for a small seller and 5-6
#: for a large one. Measured across the five live workspaces 2026-09-14:
#:
#: ===========  ==================  ===================  ==================
#: Depth        small (~4k rows/mo) median (~14k/mo)     large (~50k/mo)
#: ===========  ==================  ===================  ==================
#: 1 month      ~1 h                ~2 h                 ~5 h
#: **3 months** **~2 h**            **~5 h**             **~15 h**
#: 6 months     ~3 h                ~9 h                 ~30 h
#: ===========  ==================  ===================  ==================
#:
#: Three months because the advertising lane takes ~7 h on the same signup, so
#: for every profile but the largest seller this costs nothing anyone waits for.
#: Six would make a large seller's finances an overnight job.
#:
#: It is also what stops the walk probing history that cannot exist. At five
#: years NEVA spent three of WB's fifteen-minute windows proving that 2021 was
#: empty before it reached a single real row.
PNL_FLOOR_DAYS = 90

#: Cursor field separator. The cursor carries the whole span, not just the page
#: pointer: see the module docstring for why recomputing the span per tick
#: makes the progress bar run backwards.
_SEP = "|"

#: The endpoint the gate is keyed on.
SETTLEMENT_PATH = "/api/v5/supplier/reportDetailByPeriod"

#: Seconds before the next page. WB's own budget on this endpoint — asking
#: sooner restarts its window and makes the lane slower, not faster.
_NEXT_PAGE_SECONDS = 15 * 60 + 30

#: A tick is one request plus one ingest; the limit is a hung-call backstop.
_TICK_SOFT_LIMIT_SECONDS = 5 * 60

#: Consecutive EMPTY answers before the span is believed finished.
#:
#: One is not enough, and believing one cost NEVA two years of P&L. WB answers an
#: exhausted window with `204 No Content` — and it answers a window it is simply
#: not serving right now with the same thing. On 2026-09-11 a tick mid-span got
#: an empty body, read it as "the walk is complete", and marked a lane DONE over
#: a 715-day hole. `finance-reports.md` says it outright: never assume a day
#: once probed empty stays empty.
#:
#: A short but NON-empty page is different and still ends the walk immediately —
#: that is WB's ordinary pagination. This only guards the all-or-nothing answer.
PNL_EMPTY_STOP = 3


def _parse_cursor(cursor: str) -> tuple[date, date, int, int, date]:
    """Read the cursor back, tolerating every earlier shape it has had.

    ``span_from|span_to|rrd_id[|empties[|search_from]]``. Older lanes are always
    mid-walk when a field is added, and a parser that demanded the newest shape
    would turn every one of them into a failing tick at the moment of deploy.
    """
    parts = cursor.split(_SEP)
    span_from = date.fromisoformat(parts[0])
    span_to = date.fromisoformat(parts[1])
    rrd_id = int(parts[2])
    empties = int(parts[3]) if len(parts) > 3 and parts[3] else 0
    search_from = date.fromisoformat(parts[4]) if len(parts) > 4 and parts[4] else span_from
    return span_from, span_to, rrd_id, empties, search_from


def _format_cursor(
    span_from: date, span_to: date, rrd_id: int, empties: int, search_from: date
) -> str:
    """Write the span, page pointer, empty-streak and search floor into one string."""
    return _SEP.join(
        (
            span_from.isoformat(),
            span_to.isoformat(),
            str(rrd_id),
            str(empties),
            search_from.isoformat(),
        )
    )


#: A run of missing days longer than this is a HOLE; anything shorter is the
#: ordinary shape of settlement data.
#:
#: WB forms roughly one report a week, so rows land in clusters with quiet days
#: between them — "a day with no rows" is normal and means nothing. Measured
#: across the five real workspaces on 2026-09-11: the four healthy ones had a
#: biggest gap of 1-2 days, and the broken one had 715. There is no ambiguity in
#: the middle to tune for.
PNL_GAP_TOLERANCE_DAYS = 14

#: The most days one span may cover, so a long gap is walked in pieces.
#:
#: This is what makes "newest first" mean anything. The span is CHOSEN newest
#: first, but WB pages a window by ascending ``rrdid`` and there is no reverse —
#: so a single 90-day span would still deliver its oldest days first, and a walk
#: interrupted halfway would have left the recent months missing. Exactly what
#: happened to NEVA: stopped mid-walk it held 248 days of 2024 and not one day of
#: the summer anybody would look at.
#:
#: A month, because that is the unit the depth is discussed in — after one span
#: the seller has their most recent month, after two, two. The cost of chunking
#: is one extra request per boundary (a span ends on a short page), so ~2 extra
#: requests across the shipped 90-day depth.
PNL_SPAN_CHUNK_DAYS = 31


def next_span(
    settled_days: Sequence[date], *, search_to: date, today: date, floor: date
) -> tuple[date, date] | None:
    """The next stretch of settlement history worth asking WB for.

    The lane used to ask one question — "what is older than my oldest row?" —
    which cannot see a hole in the MIDDLE of the history. NEVA had exactly that:
    51 days of rows spanning two years, with a 715-day gap the walk had declared
    complete. Filling it by hand is not a fix, because the next lane to lose its
    place the same way would need the same hand.

    So the span is chosen from coverage instead, **newest hole first**, and no
    more than :data:`PNL_SPAN_CHUNK_DAYS` of it at a time.

    Newest first because a backfill is interrupted far more often than it is
    finished — by a deploy, a penalty block, a person deciding it has run long
    enough — and what a seller needs is this month's P&L, not the archive.
    Walking the other way, NEVA was stopped holding 248 days of 2024 and nothing
    at all from the summer.

    Days after the newest stored row are deliberately not offered. That region
    belongs to the forward harvest and its watermark, and a backfill reaching
    into it would have the two walks writing the same weeks from opposite ends.

    ``search_to`` is what stops a hole WB will never fill from being chosen for
    ever: a span concluded empty moves the ceiling BELOW it, so the search
    resumes further back rather than re-offering the same dates on the next
    tick.

    Args:
        settled_days: Distinct settlement days already stored, any order.
        search_to: Ignore holes starting after this — already concluded.
        today: Today in Moscow time.
        floor: The oldest day worth asking for. Passed in rather than derived
            from :data:`PNL_FLOOR_DAYS` so that the depth is the caller's
            decision — production reads the product's answer, while the tests
            that reproduce NEVA's two-year hole can still reach back past it.

    Returns:
        The inclusive ``(from, to)`` span to walk, or ``None`` when coverage is
        contiguous from the first report onward.
    """
    days = sorted(d for d in settled_days if d >= floor)
    if not days:
        return _chunk(floor, min(search_to, today - timedelta(days=1)), floor)

    gaps: list[tuple[date, date]] = []
    # A hole before the oldest row we hold.
    if (days[0] - floor).days > PNL_GAP_TOLERANCE_DAYS:
        gaps.append((floor, days[0] - timedelta(days=1)))
    # Holes between stored days. Days AFTER the newest row are deliberately not
    # offered: that region belongs to the forward harvest and its watermark.
    for earlier, later in pairwise(days):
        if (later - earlier).days - 1 > PNL_GAP_TOLERANCE_DAYS:
            gaps.append((earlier + timedelta(days=1), later - timedelta(days=1)))

    # Newest first. `search_to` is a ceiling that walks BACKWARDS as spans are
    # concluded, so a stretch WB will never serve is offered once and then left
    # behind — the mirror of the floor the oldest-first version moved forward.
    for gap_from, gap_to in reversed(gaps):
        if gap_from > search_to:
            continue  # already concluded; look further back
        return _chunk(gap_from, min(gap_to, search_to), floor)

    return None


def _chunk(gap_from: date, gap_to: date, floor: date) -> tuple[date, date] | None:
    """The newest :data:`PNL_SPAN_CHUNK_DAYS` of one gap, clamped to the floor."""
    if gap_to < gap_from or gap_to < floor:
        return None
    span_from = max(gap_from, floor, gap_to - timedelta(days=PNL_SPAN_CHUNK_DAYS - 1))
    return span_from, gap_to


def _roll_to_next_span(
    settled_days: Sequence[date], *, before: date, today: date, rows: int, floor: date
) -> LaneStep:
    """Finish one span by starting the next, older one, or finish the lane.

    The search resumes the day BEFORE the span just concluded — the walk moves
    backwards through history — which is what keeps a stretch WB will never
    serve from being offered again for ever.
    """
    resume = before - timedelta(days=1)
    chosen = next_span(settled_days, search_to=resume, today=today, floor=floor)
    if chosen is None:
        return LaneStep(1, 1, None, True, "История P&L собрана.", rows=rows)
    span_from, span_to = chosen
    total = max((span_to - span_from).days + 1, 1)
    return LaneStep(
        done=0,
        total=total,
        cursor=_format_cursor(span_from, span_to, 0, 0, resume),
        finished=False,
        message=f"Догружаем пропуск с {span_from} по {span_to}…",
        rows=rows,
    )
