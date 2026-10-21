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

from src.modules.finreports.repos import CostPriceRepository
from src.modules.monitoring.models import AdvertisingStatDaily
from tests.integration.finreports.conftest import (
    OTHER_WORKSPACE,
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)
from tests.integration.summary.conftest import _service

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
    """The settlement detail is touched once per request, to prove the cache.

    Aggregates are served from the rollup now, so what is left against the
    detail is the freshness check — an index-only scan, 16 MB against the
    detail's 755 — and, on a cold window, the rebuild that fills the cache. Both
    are memoised for the life of one session, which is why a page asking for the
    same window four times pays for one check.

    Before all of this the page reached its day buckets through the full P&L
    statement, which also computes a whole-window total, four drill-downs by
    WB's own reason strings and the caveat queries: nine passes to draw a chart
    that reads two of them, and a «вся история» that answered with a timeout
    instead of a page.

    The bound is deliberately loose — it is here to catch a second freshness
    check or a direct aggregate creeping back in, not to freeze a query plan.
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
    assert len(scans) <= 3, f"{len(scans)} проходов по расчёту: {cuts}"


async def test_the_daily_margin_sums_to_the_margin_card(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Σ of the chart's margin equals the card above it, with no tolerance.

    This is the assertion that was missing when the page first shipped, and the
    bug it would have caught was real: the card subtracted
    advertising twice — once as WB's weekly invoice, already inside «к
    перечислению», and once as the burn the statistics recorded — while the
    chart subtracted it once. One workspace, one 54-day window: the card came out
    about a third below the chart under it, the gap being the invoices to the som.

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


async def test_a_window_reaching_past_the_settlement_charges_only_what_it_earned_on(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Advertising burnt after the last settled day is not this window's cost.

    The window ends four days past anything WB has calculated — the normal shape
    of «последняя неделя», since the funnel and the promotion statistics land
    daily and settlements weekly and late. Both figures the advertising enters
    must ignore that tail: «Средний ДРР» divided seven days of spend by four
    days of revenue and read far above the worst day the chart drew, and the
    margin lost the same money twice over.

    The margin invariant is the sharper half: Σ of the chart's days must equal
    the card, and it cannot while the card subtracts advertising no day of the
    chart does. Since 2026-10-02 the cards charge WB's invoices, which only a
    settled day can carry, so the tail's burn moves neither.
    """
    window = {"date_from": WINDOW_FROM, "date_to": WINDOW_TO + timedelta(days=4)}
    before = await _service(db_session).build(db_session, workspace_id=WORKSPACE, **window)
    db_session.add(
        AdvertisingStatDaily(
            stat_date=WINDOW_TO + timedelta(days=2),
            campaign_id=2,
            app_type=1,
            nm_id=SKU_A,
            spend=Decimal("900"),
        )
    )
    await db_session.flush()

    summary = await _service(db_session).build(db_session, workspace_id=WORKSPACE, **window)

    assert summary.kpi.ad_spend == before.kpi.ad_spend
    assert summary.kpi.margin == before.kpi.margin
    assert sum(day.margin for day in summary.days if day.margin is not None) == summary.kpi.margin
