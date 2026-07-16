"""Smart one-off HISTORICAL backfill for production.

Pulls every piece of history the WildBerries APIs still serve and fills the
gaps in the local database, skipping whatever is already stored — safe to
re-run any number of times; each run resumes where the previous one stopped.

What is backfillable (and how deep):

===================  ==========================================  ==============
Data                 Source                                       Depth
===================  ==========================================  ==============
Funnel (daily)       analytics v3 sales-funnel AGGREGATE, one     365 days (the
                     call per day (``start == end``); the DAILY   documented
                     history feed only serves the last 7 days.    rolling max)
Buyout/cancel        same call — the aggregate carries matured    same
cohorts              ``buyoutCount``/``cancelCount``.
Sales / returns      statistics ``supplier/sales`` with an old    90 days (the
(sale-date)          ``dateFrom`` (one call = whole visible       documented
                     window).                                     retention)
Advertising          ``adv/v3/fullstats`` in 31-day slices,       undocumented;
(fullstats)          including COMPLETED campaigns.               probed to
                                                                  --adv-days
Search-zone slices   ``adv/v1/normquery/stats`` in the same       undocumented
                     slices, for search-placement campaigns.
Catalogue            content ``cards/list`` (current state).      n/a
Stocks, prices       NOT backfillable — WB exposes no history;    —
                     the nightly harvest accumulates them
                     forward from today.
===================  ==========================================  ==============

Rate-limit budget (why the pauses exist). Official limits are per TOKEN TIER —
personal/service/base-with-secret tokens get the first figure, a plain basic
(«Базовый») token a drastically reduced one:

* funnel aggregate: 3 req/min, 20 s interval (basic: 2 req/HOUR) → a 365-day
  pass is ≈ 2 h per workspace on a proper token;
* fullstats: 3 req/min, 20 s interval (basic: 1 req/hour), max 31-day window;
* normquery: 10 req/min (basic: 2 req/hour);
* supplier/sales: 1 req/min (basic: 1 req per 2 HOURS — the limit observed on
  this account). If the slot is spent, the phase fails fast and the next run
  picks it up. Older sales than 90 days would need the financial
  ``reportDetailByPeriod`` feed — a separate integration, not built here.

The script takes the same Redis locks as the nightly jobs so they cannot
compete for the WB budget mid-run; a run spanning 06:00-07:00 MSK simply makes
that night's harvest/cohort tasks skip once (they catch up the next night).

Run from the ``backend`` directory (``.env`` populated, migrations applied)::

    python -m scripts.backfill_history                 # everything, defaults
    python -m scripts.backfill_history --funnel-days 180 --skip-advertising
    python -m scripts.backfill_history --workspace "Main"    # one workspace

On prod (container has no shell niceties)::

    docker compose exec api python -m scripts.backfill_history
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta

from redis import Redis as SyncRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.exceptions import IntegrationError
from src.core.logging import configure_logging, get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBContentClient,
    WBStatisticsClient,
)
from src.integrations.wildberries.schemas import WBAdvertV2, WBCampaign
from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    SaleRecord,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService
from src.modules.monitoring.tasks import COHORT_REFRESH_DAYS
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
)

configure_logging()
logger = get_logger(__name__)

#: The same locks the nightly Celery jobs take — holding both keeps the
#: backfill and the scheduled tasks from competing for WB's rate budgets.
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"
_COHORT_LOCK_NAME = "monitoring:refresh_buyout_cohorts:lock"
#: Generous auto-expiry: a crashed run can never wedge the nightly schedule
#: for more than this long.
_LOCK_TIMEOUT_SECONDS = 10 * 60 * 60

#: WB statuses whose campaigns can carry historical spend: completed (7),
#: active (9), paused (11). Declined/deleting campaigns never delivered.
_BACKFILL_STATUSES: frozenset[int] = frozenset({7, 9, 11})

#: fullstats hard cap on one request's window.
_FULLSTATS_WINDOW_DAYS = 31


@dataclass
class PhaseTotals:
    """Row counters accumulated across workspaces for the final report."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, value: int) -> None:
        """Accumulate ``value`` under ``key``."""
        self.counts[key] = self.counts.get(key, 0) + value

    def render(self) -> str:
        """Human-readable ``key=value`` summary line."""
        if not self.counts:
            return "nothing to do"
        return ", ".join(f"{key}={value}" for key, value in sorted(self.counts.items()))


def _build_service(session: AsyncSession) -> IngestionService:
    """Wire the full ingestion service graph onto one session."""
    return IngestionService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
        price_repo=PriceRepository(session),
        sale_repo=SaleRepository(session),
    )


def _is_http_400(exc: IntegrationError) -> bool:
    """Whether a client error signals "window not served" (retention floor)."""
    return "error 400" in str(exc)


# --------------------------------------------------------------------------- #
# Phase 1 — sale/return records (statistics API)
# --------------------------------------------------------------------------- #
async def _backfill_sales(
    tokens: WorkspaceTokenBundle, *, nm_ids: list[int], sales_from: date, totals: PhaseTotals
) -> None:
    """One deep ``supplier/sales`` pull (full visible window in a single call).

    The nightly harvest calls this feed with ``changed_since = window start``
    (7 days), which only picks up RECENTLY CHANGED records — months-old sales
    never re-enter it, so history must be pulled once with an old ``dateFrom``.

    Skips itself when the DB already holds sales older than the requested
    horizon (± a month) — the marker that a previous backfill succeeded. On
    the ~1-request-per-2-hours limiter the client fails fast; the phase is
    then simply reported as pending for the next run.
    """
    async with AsyncSessionLocal() as session:
        oldest = await session.scalar(
            select(func.min(SaleRecord.sale_date)).where(SaleRecord.nm_id.in_(nm_ids))
        )
    if oldest is not None and oldest <= sales_from + timedelta(days=30):
        logger.info(
            "Sales history already reaches %s (<= %s + 30d); skipping the deep pull.",
            oldest,
            sales_from,
        )
        return

    if not tokens.statistics:
        logger.warning("Workspace '%s' has no statistics token; sales skipped.", tokens.name)
        return

    async with WBStatisticsClient(settings, token=tokens.statistics) as client:
        try:
            records = await client.fetch_sales(changed_since=sales_from)
        except IntegrationError as exc:
            logger.warning(
                "Deep sales pull unavailable now (%s). The ~2h statistics slot is "
                "likely spent — re-run the script later to pick this phase up.",
                exc,
            )
            return
        # Fetch + ingest stay in ONE process run: losing the payload after a
        # successful fetch would waste a whole 2-hour rate-limit slot.
        async with AsyncSessionLocal() as session:
            service = _build_service(session)
            count = await service.ingest_sales(records)
            await session.commit()
    totals.add("sales_rows", count)
    logger.info("Sales backfill ingested %d records (dateFrom=%s).", count, sales_from)


# --------------------------------------------------------------------------- #
# Phase 2 — daily funnel + matured cohorts (analytics aggregate, 1 call/day)
# --------------------------------------------------------------------------- #
async def _funnel_coverage(
    session: AsyncSession, *, nm_ids: list[int], since: date
) -> dict[date, dict[int, bool]]:
    """Existing funnel rows per day: ``{day: {nm_id: cancel_count is set}}``."""
    stmt = select(
        SalesFunnelDaily.stat_date, SalesFunnelDaily.nm_id, SalesFunnelDaily.cancel_count
    ).where(SalesFunnelDaily.nm_id.in_(nm_ids), SalesFunnelDaily.stat_date >= since)
    result = await session.execute(stmt)
    coverage: dict[date, dict[int, bool]] = {}
    for stat_date, nm_id, cancel_count in result.all():
        coverage.setdefault(stat_date, {})[nm_id] = cancel_count is not None
    return coverage


async def _backfill_funnel(
    tokens: WorkspaceTokenBundle,
    *,
    nm_ids: list[int],
    days: int,
    pause: float,
    empty_stop: int,
    totals: PhaseTotals,
) -> None:
    """Reconstruct the daily funnel series day-by-day from the aggregate.

    Walks from yesterday backwards. Per day, ONE aggregate call answers for
    the whole catalogue; its rows are split into

    * UPDATEs — ``(day, nm)`` already stored: refresh the matured
      ``buyout_count``/``cancel_count`` (heals days that froze at ≤7-day
      maturity before the cohort pipeline existed);
    * INSERTs — ``(day, nm)`` absent: write the full funnel row (the only way
      to obtain days older than the 7-day daily-history window).

    Skip rules make re-runs cheap: a day inside the nightly cohort window is
    the scheduled task's job; a day whose rows all carry a ``cancel_count`` was
    already healed by a previous run. Walking stops early at the WB retention
    floor (HTTP 400) or after ``empty_stop`` consecutive zero-activity days
    (predating the seller's first trade).
    """
    if not tokens.analytics:
        logger.warning("Workspace '%s' has no analytics token; funnel skipped.", tokens.name)
        return

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    wanted = set(nm_ids)

    async with AsyncSessionLocal() as session:
        coverage = await _funnel_coverage(session, nm_ids=nm_ids, since=start)

    empty_streak = 0
    async with WBAnalyticsClient(settings, token=tokens.analytics) as client:
        for offset in range(days):
            day = end - timedelta(days=offset)
            existing = coverage.get(day, {})
            if existing and offset < COHORT_REFRESH_DAYS:
                continue  # the nightly cohort task owns the maturing window
            if existing and all(existing.values()):
                empty_streak = 0
                continue  # healed by a previous run — resume point
            try:
                rows = await client.fetch_funnel_cohort_day(day=day)
            except IntegrationError as exc:
                if _is_http_400(exc):
                    logger.info("WB stops serving the aggregate at %s; funnel done.", day)
                    break
                logger.warning("Funnel day %s failed (%s); continuing.", day, exc)
                continue

            async with AsyncSessionLocal() as session:
                service = _build_service(session)
                updated = inserted = 0
                if existing:
                    updated = await service.ingest_funnel_cohorts(day, rows, nm_ids=set(existing))
                inserted = await service.ingest_funnel_backfill(
                    day, rows, nm_ids=wanted - set(existing)
                )
                await session.commit()
            totals.add("funnel_rows_inserted", inserted)
            totals.add("funnel_cohorts_updated", updated)

            if inserted == 0 and not existing:
                empty_streak += 1
                if empty_streak >= empty_stop:
                    logger.info(
                        "%d consecutive zero-activity days before %s — assuming this "
                        "predates the first trade; funnel done.",
                        empty_streak,
                        day,
                    )
                    break
            else:
                empty_streak = 0
            await asyncio.sleep(pause)  # ~1 req/20s surface


# --------------------------------------------------------------------------- #
# Phase 3 — advertising fullstats + search-zone slices, in 31-day windows
# --------------------------------------------------------------------------- #
def _window_slices(*, end: date, days: int) -> list[tuple[date, date]]:
    """Inclusive 31-day-max windows from ``end`` walking backwards."""
    slices: list[tuple[date, date]] = []
    hi = end
    floor = end - timedelta(days=days - 1)
    while hi >= floor:
        lo = max(hi - timedelta(days=_FULLSTATS_WINDOW_DAYS - 1), floor)
        slices.append((lo, hi))
        hi = lo - timedelta(days=1)
    return slices


def _search_pairs_for(
    adverts: list[WBAdvertV2], campaign_ids: set[int], nm_ids: set[int]
) -> list[tuple[int, int]]:
    """(campaign, SKU) pairs whose search-zone slice is worth requesting."""
    pairs: set[tuple[int, int]] = set()
    for advert in adverts:
        if advert.campaign_id not in campaign_ids or not advert.settings.placements.search:
            continue
        for setting in advert.nm_settings:
            if setting.nm_id in nm_ids:
                pairs.add((advert.campaign_id, setting.nm_id))
    return sorted(pairs)


async def _min_dates_by_campaign(
    session: AsyncSession, model: type[AdvertisingStatDaily] | type[AdvertisingSearchStatDaily]
) -> dict[int, date]:
    """Earliest stored ``stat_date`` per campaign for a fact table."""
    stmt = select(model.campaign_id, func.min(model.stat_date)).group_by(model.campaign_id)
    result = await session.execute(stmt)
    return dict(result.tuples().all())


async def _backfill_advertising(
    tokens: WorkspaceTokenBundle,
    *,
    nm_ids: list[int],
    days: int,
    pause: float,
    totals: PhaseTotals,
) -> None:
    """Backfill fullstats and normquery history for ALL delivering campaigns.

    Unlike the nightly harvest (active/paused only — nothing else has *recent*
    data), history belongs mostly to COMPLETED campaigns, so status 7 joins the
    set. Coverage is judged per campaign by its earliest stored row: a window
    already inside coverage is skipped, so re-runs only touch real gaps.
    Campaigns with no stored rows are (re-)requested every run — WB answers
    empty cheaply and the ingestion sweep keeps it idempotent.
    """
    if not tokens.advertising:
        logger.warning("Workspace '%s' has no advertising token; ads skipped.", tokens.name)
        return

    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        campaigns: list[WBCampaign] = await client.list_campaigns()
        adverts: list[WBAdvertV2] | None
        try:
            adverts = await client.list_adverts()
        except IntegrationError as exc:
            logger.warning("adverts-v2 failed (%s); campaign settings not refreshed.", exc)
            adverts = None

        async with AsyncSessionLocal() as session:
            service = _build_service(session)
            await service.ingest_campaigns(campaigns, adverts)
            await session.commit()

        target_ids = {c.campaign_id for c in campaigns if c.status in _BACKFILL_STATUSES}
        if not target_ids:
            logger.info("No campaigns with historical potential; advertising done.")
            return

        end = moscow_today() - timedelta(days=1)
        slices = _window_slices(end=end, days=days)

        async with AsyncSessionLocal() as session:
            full_cov = await _min_dates_by_campaign(session, AdvertisingStatDaily)
            search_cov = await _min_dates_by_campaign(session, AdvertisingSearchStatDaily)

        pairs = _search_pairs_for(adverts or [], target_ids, set(nm_ids))

        for lo, hi in slices:
            # fullstats: campaigns whose stored history does not reach lo yet.
            needed = sorted(cid for cid in target_ids if cid not in full_cov or full_cov[cid] > lo)
            if needed:
                try:
                    stats = await client.fetch_full_stats(
                        campaign_ids=needed, date_from=lo, date_to=hi
                    )
                except IntegrationError as exc:
                    # NOT a stop signal: WB also answers 400 when every
                    # requested campaign had zero impressions in the window
                    # (per the WB dev forum) — deeper windows may still hold
                    # data for other campaigns.
                    logger.warning("fullstats %s..%s failed (%s); continuing.", lo, hi, exc)
                    stats = []
                if stats:
                    async with AsyncSessionLocal() as session:
                        service = _build_service(session)
                        count = await service.ingest_advertising(stats, window=(lo, hi))
                        await session.commit()
                    totals.add("advertising_rows", count)
                await asyncio.sleep(pause)  # ~1 req/min surface

            # normquery: same window, search-placement campaigns not yet covered.
            slice_pairs = [
                (cid, nm) for cid, nm in pairs if cid not in search_cov or search_cov[cid] > lo
            ]
            if slice_pairs:
                try:
                    items = await client.fetch_search_zone_stats(
                        pairs=slice_pairs, date_from=lo, date_to=hi
                    )
                except IntegrationError as exc:
                    logger.warning("normquery %s..%s failed (%s); continuing.", lo, hi, exc)
                    items = None
                if items is not None:
                    async with AsyncSessionLocal() as session:
                        service = _build_service(session)
                        count = await service.ingest_search_stats(
                            items,
                            window=(lo, hi),
                            requested_campaign_ids=sorted({cid for cid, _ in slice_pairs}),
                        )
                        await session.commit()
                    totals.add("search_zone_rows", count)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def _backfill_workspace(tokens: WorkspaceTokenBundle, args: argparse.Namespace) -> None:
    """Run every requested phase for one workspace, isolating failures."""
    logger.info("=== Backfill for workspace '%s' ===", tokens.name)
    totals = PhaseTotals()

    # Catalogue first: it registers SKU ownership (product_card.workspace_id),
    # which every phase below and every tenant-scoped read depends on.
    if not tokens.content:
        logger.warning("Workspace '%s' has no content token; cannot discover SKUs.", tokens.name)
        return
    async with WBContentClient(settings, token=tokens.content) as content:
        cards = await content.fetch_all_cards()
    nm_ids = [card.nm_id for card in cards]
    logger.info("Discovered %d SKUs for '%s'.", len(nm_ids), tokens.name)
    if not nm_ids:
        return
    async with AsyncSessionLocal() as session:
        service = _build_service(session)
        catalog = await service.ingest_catalog(cards, workspace_id=tokens.workspace_id)
        await session.commit()
    totals.add("product_cards", catalog.product_card_rows)

    today = moscow_today()
    if not args.skip_sales:
        await _backfill_sales(
            tokens,
            nm_ids=nm_ids,
            sales_from=today - timedelta(days=args.sales_days),
            totals=totals,
        )
    if not args.skip_funnel:
        await _backfill_funnel(
            tokens,
            nm_ids=nm_ids,
            days=args.funnel_days,
            pause=args.funnel_pause,
            empty_stop=args.empty_stop,
            totals=totals,
        )
    if not args.skip_advertising:
        await _backfill_advertising(
            tokens,
            nm_ids=nm_ids,
            days=args.adv_days,
            pause=args.adv_pause,
            totals=totals,
        )

    logger.info("=== Workspace '%s' done: %s ===", tokens.name, totals.render())
    logger.info(
        "Reminder: stocks and prices have NO history at WB — they accumulate "
        "forward from the daily harvest snapshots."
    )


async def _run(args: argparse.Namespace) -> None:
    """Load workspaces and run the backfill for each requested one."""
    try:
        async with AsyncSessionLocal() as session:
            bundles = await load_workspace_token_bundles(session)
        if args.workspace:
            bundles = [b for b in bundles if b.name == args.workspace]
            if not bundles:
                raise SystemExit(f"No workspace named '{args.workspace}' with stored tokens.")
        if not bundles:
            raise SystemExit("No workspaces with stored WB tokens; nothing to backfill.")
        for bundle in bundles:
            try:
                await _backfill_workspace(bundle, args)
            except Exception:  # isolate workspaces from each other
                logger.exception("Backfill failed for workspace '%s'.", bundle.name)
    finally:
        await engine.dispose()


def main() -> None:
    """Parse arguments, take the scheduler locks, and drive the backfill."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", help="Backfill only the named workspace.")
    parser.add_argument(
        "--funnel-days",
        type=int,
        default=365,
        help="How many days of daily funnel history to reconstruct (default 365; "
        "walking stops earlier at WB's retention floor).",
    )
    parser.add_argument(
        "--adv-days",
        type=int,
        default=180,
        help="How many days of advertising history to request (default 180).",
    )
    parser.add_argument(
        "--sales-days",
        type=int,
        default=90,
        help="dateFrom horizon for the deep supplier/sales pull (default 90 — "
        "WB documents 90-day retention for this feed; older is not served).",
    )
    parser.add_argument(
        "--funnel-pause",
        type=float,
        default=20.0,
        help="Pause between funnel aggregate calls, seconds (default 20 ≈ the limiter).",
    )
    parser.add_argument(
        "--adv-pause",
        type=float,
        default=60.0,
        help="Pause between fullstats windows, seconds (default 60 ≈ the limiter).",
    )
    parser.add_argument(
        "--empty-stop",
        type=int,
        default=45,
        help="Stop the funnel walk after this many consecutive zero-activity days "
        "(assumed to predate the seller's first trade; default 45).",
    )
    parser.add_argument("--skip-sales", action="store_true")
    parser.add_argument("--skip-funnel", action="store_true")
    parser.add_argument("--skip-advertising", action="store_true")
    args = parser.parse_args()

    # Hold the nightly jobs' locks for the whole run: the backfill and the
    # scheduled harvest/cohort tasks share the same per-seller WB rate budgets
    # and would starve each other if they overlapped.
    redis = SyncRedis.from_url(settings.redis_url)
    harvest_lock = redis.lock(_HARVEST_LOCK_NAME, timeout=_LOCK_TIMEOUT_SECONDS, blocking=False)
    cohort_lock = redis.lock(_COHORT_LOCK_NAME, timeout=_LOCK_TIMEOUT_SECONDS, blocking=False)
    if not harvest_lock.acquire(blocking=False):
        raise SystemExit("A harvest is running (harvest_all lock held); try again later.")
    if not cohort_lock.acquire(blocking=False):
        harvest_lock.release()
        raise SystemExit("A cohort pass is running (its lock is held); try again later.")

    try:
        asyncio.run(_run(args))
    finally:
        for lock in (harvest_lock, cohort_lock):
            try:
                lock.release()
            except Exception:  # already expired — nothing to do
                logger.warning("A scheduler lock already expired at release time.")
        redis.close()


if __name__ == "__main__":
    main()
