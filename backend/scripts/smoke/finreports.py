"""P&L: the period list, the per-SKU report for the default week, the stock balance.

What ``PnlView`` asks for when it opens (``frontend/src/modules/finreports/store.js``):
``GET /finreports/weeks`` for the span the statement covers, then
``GET /finreports/pnl/skus`` for its last seven days, and ``GET /finreports/balance``
for the newest stock day in the section under the table. The services are built
by ``finreports/deps``' own provider functions, and the report gets the nine
monitoring figures its route resolves, so a request and the probe run the same code.

**The report is opened only when that is a read.** It is served from the
settlement rollup, and a read over days the rollup does not cover REBUILDS them
(``finreports/repos/pnl/rollup.py``) — a write, which the probe's read-only
session refuses with an error. The days go stale whenever a harvest rewrites
them, until somebody opens them, and ALL of them go when a migration that
changes a money rule empties the rollup; the worker that warms it back up is
started after this probe. So the probe asks the rollup first, with the same
row-count check the read would make, and over a stale window reports the
report as skipped by name rather than failing a sound release or writing.

Not opened: ``GET /finreports/harvest``, the freshness line. It reads Redis
rather than rows, and the SPA drops the line, not the page, when it fails.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke.report import PageSkipped, SmokeReport, attempt
from src.modules.finreports.deps import get_balance_service, get_sku_report_service
from src.modules.finreports.repos import (
    BalancePinRepository,
    CostPriceRepository,
    DailySettlementRepository,
    FinancialReportRepository,
    PnlRepository,
    SettlementUploadRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.finreports.schemas import WeeksResponse
from src.modules.finreports.services import PeriodService
from src.modules.monitoring.contract import (
    ad_bonus_coverage,
    ad_bonus_unknown_types,
    ad_coverage,
    funnel_coverage,
    load_ad_bonus_by_nm,
    load_ad_spend_by_nm,
    load_buyouts_by_nm,
    load_card_photos,
    load_orders_by_nm,
    load_stock_by_warehouse,
    load_vendor_codes,
    stock_day_span,
)

#: The window the page opens on: the last seven days of the span (store.js,
#: ``DEFAULT_DAYS``).
DEFAULT_DAYS = 7


def default_window(weeks: WeeksResponse) -> tuple[date, date] | None:
    """The window ``PnlView`` asks for on a first visit; ``None`` before any report.

    The span runs from the oldest weekly report to the newest settled day, the
    provisional daily tail included, and the window is its last seven days held
    inside it — ``presetWindow`` in ``frontend/src/core/utils/calendarModel.js``.
    A seller's remembered period lives in their browser and is no business of
    the probe's.
    """
    if not weeks.weeks:
        return None
    first = min(week.date_from for week in weeks.weeks)
    last = weeks.provisional_through or max(week.date_to for week in weeks.weeks)
    return max(last - timedelta(days=DEFAULT_DAYS - 1), first), last


def _weeks_service(session: AsyncSession) -> PeriodService:
    """``get_period_service``, built on the probe's own session."""
    return PeriodService(
        report_repo=FinancialReportRepository(session),
        daily_repo=DailySettlementRepository(session),
        upload_repo=SettlementUploadRepository(session),
    )


async def check_pnl(session: AsyncSession, report: SmokeReport, *, workspace_id: uuid.UUID) -> None:
    """Open the P&L page the way the SPA does on a first visit."""
    pnl_repo, cost_repo = PnlRepository(session), CostPriceRepository(session)
    skus = get_sku_report_service(pnl_repo, cost_repo, SkuExclusionRepository(session))
    balances = get_balance_service(pnl_repo, cost_repo, BalancePinRepository(session))
    window: tuple[date, date] | None = None

    async def weeks() -> int:
        nonlocal window
        answer = await _weeks_service(session).list_weeks(workspace_id=workspace_id)
        answer.model_dump_json()
        window = default_window(answer)
        return len(answer.weeks)

    async def statement() -> int:
        if window is None:
            raise PageSkipped(
                "no settlement period to open it on" if listed else "its period list broke"
            )
        start, end = window
        behind = await SettlementRollup(session).stale_days(
            workspace_id=workspace_id, date_from=start, date_to=end
        )
        if behind:
            raise PageSkipped(
                f"the settlement rollup is behind on {len(behind)} of its days, "
                "and opening it would rebuild them — a write"
            )
        answer = await skus.get_report(
            workspace_id=workspace_id,
            date_from=start,
            date_to=end,
            orders=await load_orders_by_nm(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            buyouts=await load_buyouts_by_nm(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            ad_spend=await load_ad_spend_by_nm(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            ad_bonus=await load_ad_bonus_by_nm(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            bonus_span=await ad_bonus_coverage(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            unknown_funding=await ad_bonus_unknown_types(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            funnel_span=await funnel_coverage(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            ad_span=await ad_coverage(
                session, workspace_id=workspace_id, date_from=start, date_to=end
            ),
            photos=await load_card_photos(session, workspace_id=workspace_id),
        )
        answer.model_dump_json()
        return len(answer.rows)

    async def balance() -> int:
        span = await stock_day_span(session, workspace_id=workspace_id)
        day = span[1] or date.today()
        answer = await balances.get_balance(
            workspace_id=workspace_id,
            stat_date=day,
            stock=await load_stock_by_warehouse(session, workspace_id=workspace_id, stat_date=day),
            vendor_codes=await load_vendor_codes(session, workspace_id=workspace_id),
            span=span,
        )
        answer.model_dump_json()
        return len(answer.rows)

    listed = await attempt(session, report, "P&L weeks", weeks)
    await attempt(session, report, "P&L report", statement)
    await attempt(session, report, "P&L balance", balance)


__all__ = ["DEFAULT_DAYS", "check_pnl", "default_window"]
