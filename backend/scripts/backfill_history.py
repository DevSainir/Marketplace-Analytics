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
  picks it up. Older sales than 90 days would need the financial realization
  report (``reportDetailByPeriod`` then, finance-api ``sales-reports`` since
  2026-09-22) — the finreports P&L backfill, not this script.

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
from datetime import timedelta

from redis import Redis as SyncRedis

from scripts.backfill.advertising import _backfill_advertising
from scripts.backfill.common import PhaseTotals, _build_service
from scripts.backfill.funnel import _backfill_funnel
from scripts.backfill.sales import _backfill_sales
from scripts.backfill.write_offs import _backfill_write_offs
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBContentClient
from src.modules.workspaces.contract import WorkspaceTokenBundle, load_workspace_token_bundles

logger = get_logger(__name__)


#: The same locks the nightly Celery jobs take — holding both keeps the
#: backfill and the scheduled tasks from competing for WB's rate budgets.
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"
_COHORT_LOCK_NAME = "monitoring:refresh_buyout_cohorts:lock"
#: Generous auto-expiry: a crashed run can never wedge the nightly schedule
#: for more than this long.
_LOCK_TIMEOUT_SECONDS = 10 * 60 * 60

__all__ = ["PhaseTotals", "_backfill_funnel", "main"]


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
    # Runs after fullstats on purpose: the bonus is allocated to SKUs in
    # proportion to the spend fullstats booked, so a window with a ledger and no
    # spend rows yet would drop its bonuses on the floor.
    if not args.skip_write_offs:
        await _backfill_write_offs(
            tokens,
            days=args.write_off_days,
            pause=args.write_off_pause,
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
    parser.add_argument(
        "--write-off-days",
        type=int,
        default=760,
        help="How far back to walk WB's advertising write-off ledger "
        "(default 760 — WB serves it to at least 2024-08).",
    )
    parser.add_argument(
        "--write-off-pause",
        type=float,
        default=20.0,
        help="Pause between write-off windows, seconds (default 20 ≈ the limiter).",
    )
    parser.add_argument("--skip-advertising", action="store_true")
    parser.add_argument("--skip-write-offs", action="store_true")
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
