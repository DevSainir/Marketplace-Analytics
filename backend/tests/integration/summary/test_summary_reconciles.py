"""«Сводка» against real SQL: does it agree with the report it is derived from?

The arithmetic is unit-tested against hand-written figures. Two things only a
real database can prove, and both are new SQL:

* the **day** cut of the settlement partitions the same rows the window total
  does, so the chart and the cards cannot disagree about one seller's revenue;
* the whole-workspace daily loaders go through the ``product_card`` semijoin,
  so another tenant's funnel and advertising never reach this page.

Shares the miniature week in ``tests/integration/finreports/conftest.py``. Its
account-level rows — storage, the advertising invoice, the filler operation —
are what make this worth asserting: a summary that smeared them over SKUs would
still total correctly and be wrong in every bar.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.services import PnlService
from src.modules.finreports.services.pnl import SkuReportService
from src.modules.monitoring.contract import load_ad_days, load_order_days
from src.modules.monitoring.models import AdvertisingStatDaily, ProductCard, SalesFunnelDaily
from src.modules.summary.services import SummaryService
from tests.integration.finreports.conftest import (
    OTHER_WORKSPACE,
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)

pytestmark = pytest.mark.integration


@contextmanager
def counting(session: AsyncSession) -> Iterator[list[str]]:
    """Record every statement the session issues inside the block."""
    seen: list[str] = []

    def _record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        seen.append(statement)

    # `get_bind()` on an async session hands back the SYNC engine underneath —
    # which is the one that emits the event.
    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _service(session: AsyncSession) -> SummaryService:
    """Wire the summary on the test session, through the real finreports services."""
    pnl_repo = PnlRepository(session)
    cost_repo = CostPriceRepository(session)
    return SummaryService(
        pnl=PnlService(
            pnl_repo=pnl_repo,
            cost_repo=cost_repo,
            report_repo=FinancialReportRepository(session),
        ),
        skus=SkuReportService(
            pnl_repo=pnl_repo,
            cost_repo=cost_repo,
            exclusion_repo=SkuExclusionRepository(session),
        ),
    )


@pytest.fixture
async def catalogued(db_session: AsyncSession, seeded: None) -> None:
    """The week's SKUs, plus one funnel and one advertising day each.

    Both monitoring tables are keyed by ``nm_id`` alone, so a card row is what
    ties them to a workspace at all — which is exactly the join under test.
    """
    db_session.add_all(
        [
            ProductCard(nm_id=SKU_A, workspace_id=WORKSPACE, vendor_code="sku-a"),
            ProductCard(nm_id=SKU_B, workspace_id=WORKSPACE, vendor_code="sku-b"),
            SalesFunnelDaily(stat_date=WINDOW_FROM, nm_id=SKU_A, order_count=40, buyout_count=12),
            SalesFunnelDaily(stat_date=WINDOW_TO, nm_id=SKU_B, order_count=60, buyout_count=18),
            AdvertisingStatDaily(
                stat_date=WINDOW_FROM,
                campaign_id=1,
                app_type=1,
                nm_id=SKU_A,
                spend=Decimal("150"),
            ),
        ]
    )
    await db_session.flush()


async def test_the_daily_revenue_sums_to_the_windows_revenue(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Σ of the chart's days equals the card above it, with no tolerance.

    The two come from different queries — one grouped by settlement date, one
    not — and a seller reading a total that does not match the shape under it
    has no way to tell which half is lying.
    """
    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert sum(day.revenue_paid for day in summary.days) == summary.kpi.revenue_paid


async def test_the_window_is_not_scanned_more_times_than_it_has_to_be(
    db_session: AsyncSession, catalogued: None
) -> None:
    """One window, a handful of passes — not one pass per figure on the page.

    Each statement here is a scan of the settlement rows, and on this service's
    largest кабинет one pass over the full history measures ~7 s. The page used
    to reach the day buckets through the full P&L statement, which also computes
    a whole-window total, four drill-downs by WB's own reason strings and the
    caveat queries — nine passes to draw a chart that reads two of them, and a
    «вся история» that answered with a timeout instead of a page.

    The bound is deliberately loose: it is here to catch a second `get_statement`
    creeping back in, not to freeze the query plan.
    """
    with counting(db_session) as statements:
        await _service(db_session).build(
            db_session, workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
        )

    scans = [
        text
        for text in statements
        if text.lstrip().upper().startswith("SELECT") and "logistics_transaction" in text
    ]
    # The GROUP BY of each, which is what names the pass that ran.
    cuts = [text.split("GROUP BY")[1].strip()[:60] if "GROUP BY" in text else "—" for text in scans]
    assert len(scans) <= 6, f"{len(scans)} проходов по расчёту: {cuts}"


async def test_the_daily_margin_sums_to_the_margin_card(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Σ of the chart's margin equals the card above it, with no tolerance.

    This is the assertion that was missing when the page first ran on live
    data, and the bug it would have caught was real: the card subtracted
    advertising twice — once as WB's weekly invoice, already inside «к
    перечислению», and once as the burn the statistics recorded — while the
    chart subtracted it once. One кабинет, one 54-day window: 3 161 239 on the
    card against 4 134 120 under it, the gap being the invoices to the сом.

    Revenue having reconciled did not catch it, because revenue is the one
    figure the restatement does not touch.
    """
    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert summary.kpi.margin is not None
    assert sum(day.margin for day in summary.days) == summary.kpi.margin


async def test_the_days_are_the_settlement_dates_the_window_actually_has(
    db_session: AsyncSession, catalogued: None
) -> None:
    """One bucket per settlement date, labelled by that date.

    WB dates each row it calculates, so a window of weekly reports still has
    rows on most days; a cut that collapsed them to the report would draw a
    seven-day step instead of a curve.
    """
    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert [day.day for day in summary.days] == [WINDOW_FROM, WINDOW_TO]


async def test_account_level_money_is_in_the_cards_and_not_in_the_bars(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Storage and the advertising invoice raise no bar and still count.

    They carry no ``nm_id``, so every way of dividing them between SKUs is an
    invention. The bars are built from the report's rows; the cards from its
    totals, which include the account-level bucket.
    """
    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert {row.nm_id for row in summary.rows} == {SKU_A, SKU_B}
    assert sum(row.revenue_paid for row in summary.rows) == summary.kpi.revenue_paid


async def test_a_foreign_workspaces_figures_never_appear(
    db_session: AsyncSession, catalogued: None
) -> None:
    """The neighbouring tenant's 777 777 sale is invisible from this workspace.

    Both tenants' rows sit in the same week of the same table; only the
    workspace in the WHERE clause separates them.
    """
    summary = await _service(db_session).build(
        db_session,
        workspace_id=OTHER_WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert summary.kpi.revenue_paid == Decimal("777777")
    assert summary.kpi.orders is None


async def test_the_daily_loaders_are_scoped_by_the_card_semijoin(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Funnel and advertising days follow ``product_card``, not the bare nm_id.

    Neither table carries a workspace, so without the semijoin one tenant's
    orders would be summed into another's chart — WB ids are global.
    """
    mine = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )
    theirs = await load_order_days(
        db_session, workspace_id=OTHER_WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert [day.orders for day in mine] == [40, 60]
    assert theirs == []


async def test_a_day_outside_the_window_is_not_loaded(
    db_session: AsyncSession, catalogued: None
) -> None:
    """The window bounds the daily series, not just the settlement query."""
    ads = await load_ad_days(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_TO + timedelta(days=1),
        date_to=WINDOW_TO + timedelta(days=7),
    )

    assert ads == []


async def test_an_uncosted_sku_takes_the_margin_off_the_whole_page(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Deleting one cost price empties the margin card AND the margin line.

    Proven end to end rather than in the composer alone because the rule has to
    survive the repository that decides which costs exist — that is where a
    currency mismatch or a tenancy filter could quietly drop one.

    ``SKU_B`` rather than ``SKU_A``: the week cancels A's single sale with a
    refund, so its net units are zero and an unknown cost there genuinely costs
    nothing. The rule withholds on unknown COST, not on unknown SKU.
    """
    await CostPriceRepository(db_session).delete_one(workspace_id=WORKSPACE, nm_id=SKU_B)
    await db_session.flush()

    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert summary.kpi.margin is None
    assert summary.kpi.uncosted_skus == 1
    assert all(day.margin is None for day in summary.days)


async def test_a_fully_costed_window_still_reports_its_margin(
    db_session: AsyncSession, catalogued: None
) -> None:
    """The withholding is about missing costs, not a rule that never fires."""
    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
    )

    assert summary.kpi.uncosted_skus == 0
    assert summary.kpi.margin is not None
