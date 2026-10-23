"""Completeness reporting for a seeded workspace.

Split out of ``seed_workspace.py``: seeding and *proving the seed worked* are
two jobs, and only the second one has to know the shape of every table the
matrix reads.

The report exists because a partially-seeded workspace looks identical to a
complete one from the UI — the columns are simply blank, with nothing saying
whether the harvest never ran, ran and found nothing, or ran and the lagged
"Buyout rate" window points at days that predate the workspace. So this
counts what each family actually holds and prints the window each workspace
covers, turning "looks empty" into a specific missing phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import distinct, func, select

from src.core.database import AsyncSessionLocal
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
from src.modules.workspaces.contract import WorkspaceTokenBundle


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
        """Whether "Buyout rate" actually renders for the newest day.

        Having cohort rows is NOT enough: the metric reads the cohorts of
        ``[D - 21, D - 7]``, so what matters is coverage INSIDE that lagged
        window, not the total count. Reporting the total was misleading — a
        workspace seeded today has cohorts and still shows a blank column.
        """
        return self.lagged_cohort_days > 0


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
        # own: what "Buyout rate" needs is not "some cohort days" but cohort
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
        # Price DAY coverage, not just row count: the "Orders" and "Buyouts" money
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
                "'Buyout rate' reads",
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
                "  ->  'Buyout rate' WILL BE BLANK for the newest days: the "
                f"[D-{BUYOUT_LAG_START_DAYS}, D-{BUYOUT_LAG_END_DAYS}] cohort window "
                "has no data. Re-run with a larger --history-days to reach back "
                "past it."
            )
        # Not a failure — a WB limitation worth stating so it is not chased as
        # a bug: the ₽ columns are derived from the day's seller price, and WB
        # serves no price history to backfill.
        if r.funnel_days > r.price_days:
            lines.append(
                f"  ->  'Orders' / 'Buyouts' money blank on {r.funnel_days - r.price_days} "
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
