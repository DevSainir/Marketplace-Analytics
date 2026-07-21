"""Seed a workspace with EVERY data family the matrix needs, in one run.

This is the "I added a workspace, fill it in" entrypoint. It exists because the
data the UI shows comes from two independently scheduled Celery jobs, and
running only the obvious one leaves a silently incomplete workspace:

* ``monitoring.harvest_all`` (nightly 06:00 MSK) — catalogue, funnel, advertising,
  search zones, stock, prices, sale records.
* ``monitoring.refresh_buyout_cohorts`` (nightly 07:00 MSK) — the order-date
  cohorts carrying ``cancel_count``, WITHOUT which «Процент выкупа» and the
  «Выкупы, ₽» derived from it are blank. It is a separate pass because the
  daily funnel endpoint serves only the last 7 days and carries no cancel
  count at all, so maturing cohorts must be re-read day by day.

Both run here — plus a third phase the schedule cannot supply at all: a walk
back through the funnel aggregate. Without it «Процент выкупа» stays blank on a
new workspace even once cohorts exist, because the metric for display day D
reads the cohorts of ``[D - 21, D - 7]`` — days that predate the workspace. The
nightly jobs only ever maintain a rolling window forward, so those older days
have to be reconstructed once, here.

Every phase is idempotent (upserts keyed by day + SKU) and the history walk
skips days it has already healed, so re-running is safe and is the intended way
to resume after a rate-limit interruption.

Run from the ``backend`` directory (``.env`` populated, migrations applied)::

    python -m scripts.seed_workspace                       # every workspace
    python -m scripts.seed_workspace --workspace "Олег"    # just one
    python -m scripts.seed_workspace --verify-only         # report, fetch nothing

    docker compose exec api python -m scripts.seed_workspace --workspace "Олег"

**Transaction boundaries.** Each phase commits its own work; the run is NOT one
database transaction. That is deliberate: the phases span minutes of
rate-limited WB calls (the cohort pass alone is one request per day over a
22-day window), and holding a single transaction open across them would pin a
connection for the whole run and throw away every fetched row if the last call
failed. Losing an hour of WB's rate budget to a rollback is worse than a
partially-seeded workspace that a re-run completes — especially since each
phase is individually atomic and idempotent.

**History depth.** The walk reaches back ``--history-days`` (52 by default):
enough for «Процент выкупа» to render across roughly the last month. It is NOT
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
from dataclasses import dataclass, field
from datetime import date, timedelta

from redis import Redis as SyncRedis
from sqlalchemy import distinct, func, select

# The funnel-history walk is shared with the deep backfill rather than
# reimplemented: same aggregate endpoint, same skip rules, same pacing. The
# scripts differ only in how far back they reach.
from scripts.backfill_history import PhaseTotals, _backfill_funnel
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.logging import configure_logging, get_logger
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    PriceSnapshot,
    ProductCard,
    SaleRecord,
    SalesFunnelDaily,
    StockSnapshot,
)
from src.modules.monitoring.services.matrix import (
    BUYOUT_LAG_END_DAYS,
    BUYOUT_LAG_START_DAYS,
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
#: This is what makes «Процент выкупа» actually RENDER rather than merely have
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


@dataclass
class WorkspaceReport:
    """What one workspace holds after seeding, for the completeness report."""

    name: str
    skus: int = 0
    funnel_rows: int = 0
    funnel_days: int = 0
    cohort_days: int = 0
    lagged_cohort_days: int = 0
    advertising_rows: int = 0
    search_rows: int = 0
    stock_rows: int = 0
    price_rows: int = 0
    price_days: int = 0
    customer_prices: int = 0
    sale_records: int = 0
    funnel_from: date | None = None
    funnel_to: date | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def buyout_percent_ready(self) -> bool:
        """Whether «Процент выкупа» actually renders for the newest day.

        Having cohort rows is NOT enough: the metric reads the cohorts of
        ``[D - 21, D - 7]``, so what matters is coverage INSIDE that lagged
        window, not the total count. Reporting the total was misleading — a
        workspace seeded today has cohorts and still shows a blank column.
        """
        return self.lagged_cohort_days > 0


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

    # Phase 3 — funnel history. Phases 1-2 leave a workspace whose «Процент
    # выкупа» is blank for its whole first three weeks: the metric reads cohorts
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


async def _collect_report(tokens: WorkspaceTokenBundle, failures: list[str]) -> WorkspaceReport:
    """Read back what the workspace actually holds now.

    Counting from the DATABASE rather than from the phases' return values is
    the point: it reports what a reader of the app would see, so a phase that
    silently persisted nothing cannot be mistaken for success.

    Args:
        tokens: The seeded workspace's credentials (used for its id and name).
        failures: Phase failures recorded during seeding.

    Returns:
        The populated report row.
    """
    report = WorkspaceReport(name=tokens.name, failures=failures)
    async with AsyncSessionLocal() as session:
        sku_ids = (
            select(ProductCard.nm_id)
            .where(ProductCard.workspace_id == tokens.workspace_id)
            .scalar_subquery()
        )
        report.skus = (
            await session.scalar(
                select(func.count())
                .select_from(ProductCard)
                .where(ProductCard.workspace_id == tokens.workspace_id)
            )
        ) or 0
        if not report.skus:
            return report

        report.funnel_rows = (
            await session.scalar(
                select(func.count())
                .select_from(SalesFunnelDaily)
                .where(SalesFunnelDaily.nm_id.in_(sku_ids))
            )
        ) or 0
        report.funnel_days = (
            await session.scalar(
                select(func.count(distinct(SalesFunnelDaily.stat_date))).where(
                    SalesFunnelDaily.nm_id.in_(sku_ids)
                )
            )
        ) or 0
        # Cohort coverage is measured twice, because the totals lie on their
        # own: what «Процент выкупа» needs is not "some cohort days" but cohort
        # days INSIDE the lagged window the newest display day reads from.
        newest = moscow_today() - timedelta(days=1)  # WB serves no current day
        lag_from = newest - timedelta(days=BUYOUT_LAG_START_DAYS)
        lag_to = newest - timedelta(days=BUYOUT_LAG_END_DAYS)
        report.lagged_cohort_days = (
            await session.scalar(
                select(func.count(distinct(SalesFunnelDaily.stat_date))).where(
                    SalesFunnelDaily.nm_id.in_(sku_ids),
                    SalesFunnelDaily.cancel_count.is_not(None),
                    SalesFunnelDaily.stat_date.between(lag_from, lag_to),
                )
            )
        ) or 0
        report.cohort_days = (
            await session.scalar(
                select(func.count(distinct(SalesFunnelDaily.stat_date))).where(
                    SalesFunnelDaily.nm_id.in_(sku_ids),
                    SalesFunnelDaily.cancel_count.is_not(None),
                )
            )
        ) or 0
        report.funnel_from = await session.scalar(
            select(func.min(SalesFunnelDaily.stat_date)).where(SalesFunnelDaily.nm_id.in_(sku_ids))
        )
        report.funnel_to = await session.scalar(
            select(func.max(SalesFunnelDaily.stat_date)).where(SalesFunnelDaily.nm_id.in_(sku_ids))
        )
        report.advertising_rows = (
            await session.scalar(
                select(func.count())
                .select_from(AdvertisingStatDaily)
                .where(AdvertisingStatDaily.nm_id.in_(sku_ids))
            )
        ) or 0
        report.search_rows = (
            await session.scalar(
                select(func.count())
                .select_from(AdvertisingSearchStatDaily)
                .where(AdvertisingSearchStatDaily.nm_id.in_(sku_ids))
            )
        ) or 0
        report.stock_rows = (
            await session.scalar(
                select(func.count())
                .select_from(StockSnapshot)
                .where(StockSnapshot.nm_id.in_(sku_ids))
            )
        ) or 0
        report.price_rows = (
            await session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .where(PriceSnapshot.nm_id.in_(sku_ids))
            )
        ) or 0
        # Price DAY coverage, not just row count: «Заказы, ₽» and «Выкупы, ₽»
        # are derived as count x seller_price, so a day without a price snapshot
        # shows «—» however many funnel rows it has. WB serves no price history,
        # so this can only ever grow forward from the first harvest.
        report.price_days = (
            await session.scalar(
                select(func.count(distinct(PriceSnapshot.stat_date))).where(
                    PriceSnapshot.nm_id.in_(sku_ids)
                )
            )
        ) or 0
        report.customer_prices = (
            await session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .where(
                    PriceSnapshot.nm_id.in_(sku_ids),
                    PriceSnapshot.customer_price.is_not(None),
                )
            )
        ) or 0
        report.sale_records = (
            await session.scalar(
                select(func.count()).select_from(SaleRecord).where(SaleRecord.nm_id.in_(sku_ids))
            )
        ) or 0
    return report


def _render_report(reports: list[WorkspaceReport]) -> str:
    """Format the completeness report every run ends with.

    Deliberately verbose about EMPTY families: the failure this script exists
    to prevent is a workspace that looks seeded because the command exited 0.
    """
    lines: list[str] = ["", "=" * 72, "SEED REPORT", "=" * 72]
    for r in reports:
        lines.append(f"\n{r.name}")
        if not r.skus:
            lines.append("  (no SKUs — discovery found nothing or its token failed)")
            for failure in r.failures:
                lines.append(f"  FAILED  {failure}")
            continue

        window = (
            f"{r.funnel_from} .. {r.funnel_to}"
            if r.funnel_from and r.funnel_to
            else "no funnel days"
        )
        rows: list[tuple[str, int, str]] = [
            ("SKUs (catalogue)", r.skus, ""),
            ("Funnel rows", r.funnel_rows, f"{r.funnel_days} days: {window}"),
            ("Buyout cohorts", r.cohort_days, "days carrying cancel_count"),
            (
                "  ...in lag window",
                r.lagged_cohort_days,
                f"the [D-{BUYOUT_LAG_START_DAYS}, D-{BUYOUT_LAG_END_DAYS}] days "
                "«Процент выкупа» reads",
            ),
            ("Advertising rows", r.advertising_rows, ""),
            ("Search-zone rows", r.search_rows, ""),
            ("Stock rows", r.stock_rows, ""),
            (
                "Price snapshots",
                r.price_rows,
                f"{r.price_days} days, {r.customer_prices} with a customer price",
            ),
            ("Sale/return records", r.sale_records, ""),
        ]
        for label, value, note in rows:
            flag = " ok  " if value else "EMPTY"
            suffix = f"  ({note})" if note else ""
            lines.append(f"  [{flag}] {label:<22}{value:>8}{suffix}")

        if not r.buyout_percent_ready:
            lines.append(
                "  ->  «Процент выкупа» WILL BE BLANK for the newest days: the "
                f"[D-{BUYOUT_LAG_START_DAYS}, D-{BUYOUT_LAG_END_DAYS}] cohort window "
                "has no data. Re-run with a larger --history-days to reach back "
                "past it."
            )
        # Not a failure — a WB limitation worth stating so it is not chased as
        # a bug: the ₽ columns are derived from the day's seller price, and WB
        # serves no price history to backfill.
        if r.funnel_days > r.price_days:
            lines.append(
                f"  ->  «Заказы, ₽» / «Выкупы, ₽» blank on {r.funnel_days - r.price_days} "
                "older day(s): no price snapshot for them. WB serves NO price history, "
                "so those days stay blank permanently; coverage grows forward daily."
            )
        for failure in r.failures:
            lines.append(f"  FAILED  {failure}")

    lines.append("")
    lines.append(
        "Note: these are the rolling windows the nightly jobs maintain. For deep "
        "history run scripts/backfill_history.py (hours, rate-limited)."
    )
    lines.append("=" * 72)
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    """Seed the requested workspaces and report what they hold.

    Returns:
        A process exit code: non-zero when a phase failed or a workspace ended
        up without the cohort days «Процент выкупа» needs.
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
        "window «Процент выкупа» averages over, plus maturation).",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=_HISTORY_DAYS,
        help=f"Days of funnel history to reconstruct (default {_HISTORY_DAYS}). This is "
        "what makes «Процент выкупа» render on a new workspace; 0 disables the phase. "
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
