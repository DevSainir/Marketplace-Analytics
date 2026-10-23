"""Seed a workspace with EVERY data family the matrix needs, in one run.

This is the "I added a workspace, fill it in" entrypoint. It exists because the
data the UI shows comes from two independently scheduled Celery jobs, and
running only the obvious one leaves a silently incomplete workspace:

* ``monitoring.harvest_all`` (nightly 06:00 MSK) — catalogue, funnel, advertising,
  search zones, stock, prices, sale records.
* ``monitoring.refresh_buyout_cohorts`` (nightly 07:00 MSK) — the order-date
  cohorts carrying ``cancel_count``, WITHOUT which "Buyout rate" and the
  "Buyouts" money derived from it are blank. It is a separate pass because the
  daily funnel endpoint serves only the last 7 days and carries no cancel
  count at all, so maturing cohorts must be re-read day by day.

Both run here — plus a third phase the schedule cannot supply at all: a walk
back through the funnel aggregate. Without it "Buyout rate" stays blank on a
new workspace even once cohorts exist, because the metric for display day D
reads the cohorts of ``[D - 21, D - 7]`` — days that predate the workspace. The
nightly jobs only ever maintain a rolling window forward, so those older days
have to be reconstructed once, here.

Every phase is idempotent (upserts keyed by day + SKU) and the history walk
skips days it has already healed, so re-running is safe and is the intended way
to resume after a rate-limit interruption.

Run from the ``backend`` directory (``.env`` populated, migrations applied)::

    python -m scripts.seed_workspace                       # every workspace
    python -m scripts.seed_workspace --workspace "Demo"    # just one
    python -m scripts.seed_workspace --verify-only         # report, fetch nothing

    docker compose exec api python -m scripts.seed_workspace --workspace "Demo"

**Transaction boundaries.** Each phase commits its own work; the run is NOT one
database transaction. That is deliberate: the phases span minutes of
rate-limited WB calls (the cohort pass alone is one request per day over a
22-day window), and holding a single transaction open across them would pin a
connection for the whole run and throw away every fetched row if the last call
failed. Losing an hour of WB's rate budget to a rollback is worse than a
partially-seeded workspace that a re-run completes — especially since each
phase is individually atomic and idempotent.

**History depth.** The walk reaches back ``--history-days`` (52 by default):
enough for "Buyout rate" to render across roughly the last month. It is NOT
the full year WB retains — that is ``scripts/backfill_history.py``, which also
reconstructs advertising and deep sales and runs for hours. The report prints
the window each workspace actually holds, so the difference is visible rather
than assumed.

**Runtime.** Phases 1-2 take seconds; the history walk is one rate-limited call
per day walked (~20s apart), so a first seed is roughly 15-20 minutes per
workspace. Re-runs skip healed days and finish in seconds.
"""

from __future__ import annotations

import argparse
import asyncio

from redis import Redis as SyncRedis
from sqlalchemy import select

# The funnel-history walk is shared with the deep backfill rather than
# reimplemented: same aggregate endpoint, same skip rules, same pacing. The
# scripts differ only in how far back they reach.
from scripts.backfill_history import PhaseTotals, _backfill_funnel

# Seeding and proving the seed worked are two jobs; the completeness report
# owns the second one (scripts/workspace_report.py).
from scripts.workspace_report import WorkspaceReport, _collect_report, _render_report
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.logging import configure_logging, get_logger
from src.modules.monitoring.models import (
    ProductCard,
)
from src.modules.monitoring.tasks.cohorts import (
    COHORT_REFRESH_DAYS,
    _refresh_workspace_cohorts,
)
from src.modules.monitoring.tasks.discovery import _discover_and_harvest_workspace
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
)

configure_logging()
logger = get_logger(__name__)

#: The same locks the nightly Celery jobs take — holding both keeps this seed
#: and the scheduled tasks from competing for one seller's WB rate budgets.
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"
_COHORT_LOCK_NAME = "monitoring:refresh_buyout_cohorts:lock"
#: Generous auto-expiry: a crashed run can never wedge the nightly schedule for
#: more than this long.
_LOCK_TIMEOUT_SECONDS = 4 * 60 * 60

#: Rolling funnel window the nightly harvest maintains (WB's daily funnel
#: endpoint rejects windows longer than this).
_HARVEST_WINDOW_DAYS = 7

#: How many days of funnel history the seed reconstructs by default.
#:
#: This is what makes "Buyout rate" actually RENDER rather than merely have
#: rows. The metric for display day D averages the order-date cohorts of
#: ``[D - 21, D - 7]``, so a workspace whose funnel starts today shows a blank
#: column for its entire first three weeks — the lagged window points at days it
#: has no data for. Reaching back ``BUYOUT_LAG_START_DAYS`` (21) covers the
#: newest display day; this default adds a month of viewing window on top, so a
#: freshly seeded workspace shows the metric across the period a user actually
#: opens. Raise it to view further back — or run ``backfill_history.py`` for the
#: full year.
_HISTORY_DAYS = 52

#: Stop the history walk after this many consecutive zero-activity days — they
#: predate the seller's first trade, so walking further only burns rate budget.
_HISTORY_EMPTY_STOP = 45

#: Seconds between funnel-history calls; the aggregate endpoint allows ~3/min.
_HISTORY_PAUSE_SECONDS = 20.0


async def _seed_workspace(
    tokens: WorkspaceTokenBundle, *, cohort_days: int, history_days: int, history_pause: float
) -> list[str]:
    """Run every seeding phase for one workspace.

    Phases are independent: a failure in one is recorded and the rest still
    run, so a rate-limited advertising pull does not cost the cohort pass.

    Args:
        tokens: The workspace's decrypted WB credentials.
        cohort_days: How many order-date cohort days to re-read.
        history_days: How many days of funnel history to reconstruct.
        history_pause: Seconds between funnel-history calls (the limiter).

    Returns:
        Human-readable descriptions of the phases that failed (empty on success).
    """
    failures: list[str] = []

    logger.info("=== Seeding workspace '%s' ===", tokens.name)

    # Phase 1 — catalogue + funnel + advertising + stock + prices + sales.
    # Discovery runs first because every later phase is scoped to the SKUs it
    # registers.
    nm_ids: list[int] = []
    try:
        result = await _discover_and_harvest_workspace(tokens, _HARVEST_WINDOW_DAYS)
        logger.info(
            "Harvest done for '%s': %s",
            tokens.name,
            ", ".join(f"{key}={value}" for key, value in sorted(result.items())) or "no SKUs",
        )
    except Exception as exc:
        logger.warning("Harvest phase failed for '%s': %s", tokens.name, exc)
        failures.append(f"harvest: {exc}")

    async with AsyncSessionLocal() as session:
        nm_ids = list(
            (
                await session.scalars(
                    select(ProductCard.nm_id).where(ProductCard.workspace_id == tokens.workspace_id)
                )
            ).all()
        )

    # Phase 2 — buyout cohorts for the maturing window. Re-reads the days whose
    # deliveries are still being accepted or refused.
    try:
        refreshed = await _refresh_workspace_cohorts(tokens, cohort_days)
        logger.info("Cohort pass done for '%s': %d cohort days.", tokens.name, refreshed)
    except Exception as exc:
        logger.warning("Cohort phase failed for '%s': %s", tokens.name, exc)
        failures.append(f"cohorts: {exc}")

    # Phase 3 — funnel history. Phases 1-2 leave a workspace whose "Buyout
    # rate" is blank for its whole first three weeks: the metric reads cohorts
    # from [D-21, D-7], which for a brand-new workspace point at days before it
    # had any data. This walk reconstructs those older days (rows AND cohorts)
    # from the aggregate endpoint, one call per day. It is the slow phase —
    # rate-limited to ~1 call per 20s — but its skip rules make re-runs cheap.
    if not nm_ids:
        logger.warning("No SKUs for '%s'; skipping the history walk.", tokens.name)
        return failures
    if history_days <= 0:
        logger.info("History walk disabled for '%s' (--history-days 0).", tokens.name)
        return failures
    try:
        totals = PhaseTotals()
        await _backfill_funnel(
            tokens,
            nm_ids=nm_ids,
            days=history_days,
            pause=history_pause,
            empty_stop=_HISTORY_EMPTY_STOP,
            totals=totals,
        )
        logger.info("History walk done for '%s': %s", tokens.name, totals.render())
    except Exception as exc:
        logger.warning("History phase failed for '%s': %s", tokens.name, exc)
        failures.append(f"history: {exc}")

    return failures


async def _run(args: argparse.Namespace) -> int:
    """Seed the requested workspaces and report what they hold.

    Returns:
        A process exit code: non-zero when a phase failed or a workspace ended
        up without the cohort days "Buyout rate" needs.
    """
    try:
        async with AsyncSessionLocal() as session:
            bundles = await load_workspace_token_bundles(session)
        if args.workspace:
            bundles = [b for b in bundles if b.name == args.workspace]
            if not bundles:
                raise SystemExit(f"No workspace named '{args.workspace}' with stored tokens.")
        if not bundles:
            raise SystemExit("No workspaces with stored WB tokens; nothing to seed.")

        reports: list[WorkspaceReport] = []
        for bundle in bundles:
            failures: list[str] = []
            if not args.verify_only:
                # Workspaces are isolated from each other: one revoked token
                # must not stop the rest from seeding.
                try:
                    failures = await _seed_workspace(
                        bundle,
                        cohort_days=args.cohort_days,
                        history_days=args.history_days,
                        history_pause=args.history_pause,
                    )
                except Exception as exc:
                    logger.exception("Seeding failed for workspace '%s'.", bundle.name)
                    failures = [f"unexpected: {exc}"]
            reports.append(await _collect_report(bundle, failures))

        print(_render_report(reports))
        incomplete = [r for r in reports if r.failures or not r.buyout_percent_ready or not r.skus]
        return 1 if incomplete else 0
    finally:
        await engine.dispose()


def main() -> None:
    """Parse arguments, take the scheduler locks, and drive the seed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", help="Seed only the named workspace.")
    parser.add_argument(
        "--cohort-days",
        type=int,
        default=COHORT_REFRESH_DAYS,
        help=f"Order-date cohort days to re-read (default {COHORT_REFRESH_DAYS} — the "
        "window 'Buyout rate' averages over, plus maturation).",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=_HISTORY_DAYS,
        help=f"Days of funnel history to reconstruct (default {_HISTORY_DAYS}). This is "
        "what makes 'Buyout rate' render on a new workspace; 0 disables the phase. "
        "Costs ~1 rate-limited call per day walked.",
    )
    parser.add_argument(
        "--history-pause",
        type=float,
        default=_HISTORY_PAUSE_SECONDS,
        help=f"Pause between funnel-history calls, seconds (default {_HISTORY_PAUSE_SECONDS} "
        "≈ the limiter).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Fetch nothing; just report what each workspace already holds.",
    )
    args = parser.parse_args()

    if args.verify_only:
        raise SystemExit(asyncio.run(_run(args)))

    # Hold the nightly jobs' locks for the whole run: this seed and the
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
        raise SystemExit(asyncio.run(_run(args)))
    finally:
        for lock in (harvest_lock, cohort_lock):
            try:
                lock.release()
            except Exception:  # already expired — nothing to do
                logger.warning("A scheduler lock already expired at release time.")
        redis.close()


if __name__ == "__main__":
    main()
