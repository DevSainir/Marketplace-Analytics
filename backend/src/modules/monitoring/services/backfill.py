"""Walking a new workspace's monitoring history, one bounded step at a time.

Two lanes live here — the funnel aggregate and advertising fullstats — and both
are shaped by the same constraint: a backfill runs for hours beside a service
that has to keep working. So neither is a loop that runs to completion. Each
exposes :meth:`advance`, which does a **bounded** amount of work (a few days, or
one 31-day window), reports where it got to, and returns. The task that calls it
re-enqueues itself.

That shape is the whole design, and it buys three things a long-running loop
cannot:

* **Memory stays flat.** Nothing accumulates across steps; the peak is one WB
  response, and the process is free between them.
* **A worker slot is never held.** A tick is ~90 seconds. The nightly harvest
  never has to wait behind a walk that started six hours ago.
* **It survives everything.** The resume point is a row in Postgres, so a
  deploy, a restart or an OOM elsewhere costs one step, not the run.

The funnel lane does double duty and that is deliberate. It INSERTs days WB
still serves (a rolling 365) and UPDATEs matured ``buyout_count``/``cancel_count``
on days that lack them — which is «Процент выкупа», and therefore what
«Выкупы, ₽» and «ДРР от продаж» divide by. A day whose rows carry no cohort is a
blank ДРР cell on the seller's screen.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient, WBAnalyticsClient
from src.modules.monitoring.models import AdvertisingStatDaily, SalesFunnelDaily
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    AdvertisingRepository,
    AdvertisingSearchRepository,
    AdvertisingWriteOffRepository,
    CampaignRepository,
    FunnelRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.services.ingestion import IngestionService
from src.modules.workspaces.contract import LaneStep, WorkspaceTokenBundle

logger = get_logger(__name__)

#: WB serves a rolling 365 days on the funnel aggregate. Bisected live
#: 2026-09-09: `today-364` served real numbers, `today-365` answered HTTP 400.
#: Nothing older can ever be recovered, by us or anyone.
FUNNEL_DAYS = 365

#: How deep to ask advertising for. fullstats has no retention cliff (probed to
#: -1040 days, 2026-09-09), so this is simply "older than any account we have"
#: and the walk stops on per-campaign coverage rather than on a limit.
ADV_DAYS = 1100

#: fullstats caps one request at 31 days.
ADV_WINDOW_DAYS = 31

#: Campaign ids per WB request — WB's own cap on the `ids` list, and therefore
#: the size of one tick's work. The client batches internally at this number,
#: so handing it exactly this many means exactly one gated request per tick.
ADV_BATCH = 50

#: Days the funnel lane examines per tick. Four calls at ~21 s is ~85 s of work
#: — long enough to make progress, short enough that a tick never looks like a
#: stuck worker and never blocks the queue for long.
FUNNEL_DAYS_PER_TICK = 4

#: Seconds between calls inside one tick. Both aggregates refill a token every
#: ~20 s; pacing here keeps the shared Redis gate a backstop rather than the
#: thing doing the waiting.
CALL_PAUSE_SECONDS = 21.0

#: The nightly cohort pass owns the most recent days — re-reading them here
#: would spend the same budget twice on the same rows.
COHORT_WINDOW_DAYS = 22

#: The days the lane may leave to that pass: only those its NEXT run still
#: reads. The pass reads 22 days back from ITS yesterday, and the next one runs
#: tomorrow, so the oldest day of today's window has already left it. Leaving
#: all 22 lost exactly that day: the lane of 29.09.2026 left 07.09 to a pass
#: that, on 30.09, read 08.09 .. 29.09 — the day's funnel sums were never
#: fetched, and nothing said so (see ``tasks/funnel_gaps.py``).
COHORT_HANDOFF_DAYS = COHORT_WINDOW_DAYS - 1

#: Consecutive zero-activity days that mean "this predates the seller's first
#: trade". Young accounts are the common case, and without this the lane would
#: spend 300 slots proving a shop that opened in June did not trade in October.
EMPTY_STOP = 21

#: Campaign statuses that can carry historical spend: completed, active, paused.
#: Completed is the important one — history belongs mostly to finished campaigns.
_LIVE_STATUSES = frozenset({7, 9, 11})


def build_ingestion_service(session: AsyncSession) -> IngestionService:
    """Wire the full ingestion graph onto one session."""
    return IngestionService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
        advertising_cluster_repo=AdvertisingClusterRepository(session),
        advertising_write_off_repo=AdvertisingWriteOffRepository(session),
        price_repo=PriceRepository(session),
        sale_repo=SaleRepository(session),
    )


def _is_retention_floor(exc: IntegrationError) -> bool:
    """Whether a client error means "WB does not serve a window this old"."""
    return "error 400" in str(exc)


async def _funnel_coverage(
    session: AsyncSession, *, nm_ids: list[int], since: date
) -> dict[date, dict[int, bool]]:
    """Existing funnel rows per day: ``{day: {nm_id: complete}}``.

    Complete means a matured cohort AND the funnel's own money. The sums were
    first stored on 2026-09-29, so every older row lacks them, and this is what
    makes re-running the lane fill them from the same aggregate call that
    serves the cohort — no second walk, no second request per day.
    """
    stmt = select(
        SalesFunnelDaily.stat_date,
        SalesFunnelDaily.nm_id,
        SalesFunnelDaily.cancel_count,
        SalesFunnelDaily.order_sum,
    ).where(SalesFunnelDaily.nm_id.in_(nm_ids), SalesFunnelDaily.stat_date >= since)
    result = await session.execute(stmt)
    coverage: dict[date, dict[int, bool]] = {}
    for stat_date, nm_id, cancel_count, order_sum in result.all():
        complete = cancel_count is not None and order_sum is not None
        coverage.setdefault(stat_date, {})[nm_id] = complete
    return coverage


def left_to_cohort_pass(*, end: date, day: date) -> bool:
    """Whether the next nightly cohort pass still reads ``day`` (``end`` = yesterday).

    Only then may the lane skip it; see :data:`COHORT_HANDOFF_DAYS`.
    """
    return (end - day).days < COHORT_HANDOFF_DAYS


async def advance_funnel(
    tokens: WorkspaceTokenBundle,
    *,
    nm_ids: list[int],
    cursor: str | None,
    days_per_tick: int = FUNNEL_DAYS_PER_TICK,
) -> LaneStep:
    """Walk a few more days of funnel history backwards from the cursor.

    Per day, ONE aggregate call answers for the whole catalogue, and its rows
    are split two ways: ``(day, nm)`` already stored gets its matured
    ``buyout_count``/``cancel_count`` and its money refreshed, and ``(day, nm)``
    absent gets the full row inserted. The second is the only way to obtain a day older
    than the 7-day daily-history window; the first is what makes «Процент
    выкупа» exist for it.

    Days needing neither are skipped without a request, so a re-run is cheap
    and a lane resumed after a restart does not re-pay for what it already did.

    Args:
        tokens: The workspace's decrypted credentials.
        nm_ids: The SKUs this workspace owns.
        cursor: ISO date of the next day to examine; ``None`` starts at
            yesterday (WB serves no current day).
        days_per_tick: How many days this step may examine.

    Returns:
        The step's outcome. ``finished`` is set on any of the three real
        endings: the 365-day window is exhausted, WB refused an older day, or
        the seller's trading history ran out.
    """
    if not tokens.analytics:
        return LaneStep(0, 0, None, True, "Нет токена «Аналитика» — воронка пропущена.")

    end = moscow_today() - timedelta(days=1)
    floor = end - timedelta(days=FUNNEL_DAYS - 1)
    day = date.fromisoformat(cursor) if cursor else end
    if day < floor:
        return LaneStep(FUNNEL_DAYS, FUNNEL_DAYS, None, True, "Воронка собрана за 365 дней.")

    async with AsyncSessionLocal() as session:
        coverage = await _funnel_coverage(session, nm_ids=nm_ids, since=floor)

    wanted = set(nm_ids)
    examined = 0
    written = 0
    empty_streak = 0
    finished = False
    message = ""

    async with WBAnalyticsClient(settings, token=tokens.analytics) as client:
        while examined < days_per_tick and day >= floor:
            existing = coverage.get(day, {})
            # The nightly cohort pass owns the maturing window, and a day whose
            # every row already carries a cohort and its money was healed by an
            # earlier step.
            inside_cohort_window = left_to_cohort_pass(end=end, day=day)
            if existing and (inside_cohort_window or all(existing.values())):
                day -= timedelta(days=1)
                continue

            examined += 1
            try:
                rows = await client.fetch_funnel_cohort_day(day=day)
            except IntegrationError as exc:
                if _is_retention_floor(exc):
                    finished = True
                    message = f"WB отдаёт воронку только до {day + timedelta(days=1)}."
                    break
                logger.warning("[%s] funnel day %s failed (%s).", tokens.name, day, exc)
                day -= timedelta(days=1)
                continue

            async with AsyncSessionLocal() as session:
                service = build_ingestion_service(session)
                if existing:
                    written += await service.ingest_funnel_cohorts(day, rows, nm_ids=set(existing))
                inserted = await service.ingest_funnel_backfill(
                    day, rows, nm_ids=wanted - set(existing)
                )
                written += inserted
                await session.commit()

            if inserted == 0 and not existing:
                empty_streak += 1
                if empty_streak >= EMPTY_STOP:
                    finished = True
                    message = "Дошли до начала продаж — воронка собрана."
                    break
            else:
                empty_streak = 0
            day -= timedelta(days=1)
            if examined < days_per_tick and day >= floor:
                await asyncio.sleep(CALL_PAUSE_SECONDS)

    if not finished and day < floor:
        finished = True
        message = "Воронка собрана за 365 дней."
    done = (end - day).days + 1 if not finished else FUNNEL_DAYS
    return LaneStep(
        done=min(done, FUNNEL_DAYS),
        total=FUNNEL_DAYS,
        cursor=None if finished else day.isoformat(),
        finished=finished,
        message=message or f"Собираем воронку: {min(done, FUNNEL_DAYS)} из {FUNNEL_DAYS} дней.",
        rows=written,
    )


def _parse_adv_cursor(
    cursor: str | None, *, default_end: date
) -> tuple[date, int, set[int] | None]:
    """Read ``"<window end>|<batch index>|<live campaign ids>"``.

    Both older forms still parse — a bare date, and a date with a batch but no
    ids — because a lane part-way through its walk when this shipped carries one
    of them and must not restart. A ``None`` id set means "this cursor predates
    the third field"; the caller asks WB once more and the cursor it writes back
    carries the list from then on.

    Args:
        cursor: The lane's stored resume point, or ``None`` before it starts.
        default_end: Where a lane with no cursor begins.

    Returns:
        ``(window end, batch index, live campaign ids or None)``.
    """
    if not cursor:
        return default_end, 0, None
    head, _, tail = cursor.partition("|")
    batch_part, _, ids_part = tail.partition("|")
    ids = {int(i) for i in ids_part.split(",") if i} if ids_part else None
    return date.fromisoformat(head), int(batch_part) if batch_part else 0, ids


def _format_adv_cursor(window_end: date, batch: int, campaign_ids: set[int]) -> str:
    """Write the window, batch and campaign list the next tick resumes from.

    The ids ride along so no tick after the first spends a WB request
    rediscovering them. It is a few kilobytes in a ``Text`` column against one
    gated call per tick — and the walk makes hundreds of ticks.
    """
    ids = ",".join(str(i) for i in sorted(campaign_ids))
    return f"{window_end.isoformat()}|{batch}|{ids}"


async def _campaign_coverage(session: AsyncSession) -> dict[int, date]:
    """Earliest stored advertising day per campaign."""
    from sqlalchemy import func

    stmt = select(
        AdvertisingStatDaily.campaign_id, func.min(AdvertisingStatDaily.stat_date)
    ).group_by(AdvertisingStatDaily.campaign_id)
    result = await session.execute(stmt)
    return dict(result.all())  # type: ignore[arg-type]


async def advance_advertising(tokens: WorkspaceTokenBundle, *, cursor: str | None) -> LaneStep:
    """Fetch ONE 31-day window of advertising history, fullstats only.

    Deliberately no normquery/cluster call. The cluster tables are out of scope
    for a backfill by decision, and a flag defaulting to "also do clusters" is
    one forgotten argument away from spending that budget anyway.

    Coverage is judged per campaign by its earliest stored row, so a window
    every campaign already reaches is skipped without a request.

    ONE campaign batch per tick, not one window — and the difference is a lane
    that dies. ``fetch_full_stats`` splits its ids into requests of 50, each
    paced at ~20 s by the shared gate, so a window for an account with several
    hundred campaigns is eight or more gated calls inside a single task. NEVA has
    ~360: measured live 2026-09-11, its advertising tick spent 160 s+ purely
    waiting on the gate and was killed by the 300 s soft limit
    (`SoftTimeLimitExceeded`), which ends the chain exactly as it ended the P&L
    lane's. A tick must do ONE bounded unit, and for this surface the unit is a
    batch, not a window.

    Args:
        tokens: The workspace's decrypted credentials.
        cursor: ``"<window end>|<batch index>"``; ``None`` starts at yesterday.

    Returns:
        The step's outcome — one WB request's worth of work.
    """
    if not tokens.advertising:
        return LaneStep(0, 0, None, True, "Нет токена «Продвижение» — реклама пропущена.")

    end = moscow_today() - timedelta(days=1)
    floor = end - timedelta(days=ADV_DAYS - 1)
    total = -(-ADV_DAYS // ADV_WINDOW_DAYS)  # ceil
    hi, batch, known_ids = _parse_adv_cursor(cursor, default_end=end)
    if hi < floor:
        return LaneStep(total, total, None, True, "Реклама собрана полностью.")

    lo = max(hi - timedelta(days=ADV_WINDOW_DAYS - 1), floor)
    written = 0

    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        # Campaign discovery once per walk, not once per tick. The list does not
        # change while we walk backwards — the code has said so since the lane
        # was written, and then asked WB again on every single tick anyway. A
        # campaign created mid-walk has no history behind it to collect, so
        # freezing the list at the first tick loses nothing and saves one gated
        # request per tick for the rest of the walk (36 windows, up to eight
        # batches each).
        if cursor is None:
            campaigns = await client.list_campaigns()
            try:
                adverts = await client.list_adverts()
            except IntegrationError as exc:
                logger.warning("[%s] adverts-v2 failed (%s).", tokens.name, exc)
                adverts = None
            async with AsyncSessionLocal() as session:
                service = build_ingestion_service(session)
                await service.ingest_campaigns(campaigns, adverts)
                await session.commit()
            target_ids = {c.campaign_id for c in campaigns if c.status in _LIVE_STATUSES}
        elif known_ids is None:
            # A lane that started before the cursor carried the list. One last
            # discovery call, and the cursor written below carries it onward.
            campaigns = await client.list_campaigns()
            target_ids = {c.campaign_id for c in campaigns if c.status in _LIVE_STATUSES}
        else:
            target_ids = known_ids

        if not target_ids:
            return LaneStep(total, total, None, True, "Рекламных кампаний нет.")

        async with AsyncSessionLocal() as session:
            coverage = await _campaign_coverage(session)
        needed = sorted(c for c in target_ids if c not in coverage or coverage[c] > lo)
        chunk = needed[batch * ADV_BATCH : (batch + 1) * ADV_BATCH]

        if chunk:
            try:
                stats = await client.fetch_full_stats(campaign_ids=chunk, date_from=lo, date_to=hi)
            except IntegrationError as exc:
                # NOT a stop signal: WB also answers 400 when every requested
                # campaign had zero impressions in the window, and a deeper one
                # may still hold data for a campaign that ran then.
                logger.warning("[%s] fullstats %s..%s failed (%s).", tokens.name, lo, hi, exc)
                stats = []
            if stats:
                async with AsyncSessionLocal() as session:
                    service = build_ingestion_service(session)
                    written = await service.ingest_advertising(stats, window=(lo, hi))
                    await session.commit()

    # More batches left in this window? Stay on it. Otherwise step the window
    # back and start its batches from the beginning.
    more_batches = len(needed) > (batch + 1) * ADV_BATCH
    if more_batches:
        next_hi, next_batch = hi, batch + 1
    else:
        next_hi, next_batch = lo - timedelta(days=1), 0
    finished = not more_batches and next_hi < floor
    done = min(total, ((end - lo).days // ADV_WINDOW_DAYS) + 1)
    return LaneStep(
        done=total if finished else done,
        total=total,
        cursor=None if finished else _format_adv_cursor(next_hi, next_batch, target_ids),
        finished=finished,
        message=(
            "Реклама собрана полностью."
            if finished
            else f"Собираем рекламу: с {lo}, окно {done} из {total}."
        ),
        rows=written,
    )
