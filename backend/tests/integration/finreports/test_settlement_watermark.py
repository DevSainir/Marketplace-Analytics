"""The watermark is the walk's own, and it only ever moves forward.

Two properties that only a real database can show, both of them the reason this
table exists rather than a derived `max()` over the report headers:

* **A report header cannot move it.** The header carries the period WB *states*
  and is written from the first page that lands, so it reaches the end of a week
  the walk has barely started. That is precisely what silently skipped five of
  six days on 2026-09-07, and the fix is that the two numbers now come from
  different places and are allowed to disagree.
* **It never rewinds.** Two harvests can overlap — the hourly tick holds a lock
  but a «Обновить» for one workspace does not wait for it — and the loser of
  that race must not drag the mark back to its own older span, which would
  re-open a window that had already been closed.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos import (
    FinancialReportRepository,
    SettlementWatermarkRepository,
)

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-000000000ce1")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-000000000ce2")


async def test_a_never_walked_workspace_has_no_watermark(db_session: AsyncSession) -> None:
    """Absence reads as "never harvested", which is a reason to walk.

    The caller must not be able to confuse it with a covered span — a `None`
    that defaulted to today would skip a seller's whole history in silence.
    """
    mark = await SettlementWatermarkRepository(db_session).get(workspace_id=WORKSPACE)

    assert mark is None


async def test_the_watermark_never_moves_backwards(db_session: AsyncSession) -> None:
    """A later, older write loses to the day already recorded."""
    repo = SettlementWatermarkRepository(db_session)
    await repo.advance_to(workspace_id=WORKSPACE, day=date(2026, 9, 14))

    returned = await repo.advance_to(workspace_id=WORKSPACE, day=date(2026, 9, 7))

    assert returned == date(2026, 9, 14)
    assert await repo.get(workspace_id=WORKSPACE) == date(2026, 9, 14)


async def test_a_report_claiming_a_later_period_does_not_move_the_watermark(
    db_session: AsyncSession,
) -> None:
    """The incident's exact shape: the header runs ahead, the mark does not.

    `latest_settled_date` still answers 06.09 — it is the report-facing figure
    the UI announces — while the walk's mark stays at the day it actually
    finished. The freshness gate reads the latter, so the unfetched days are
    still asked for.
    """
    repo = SettlementWatermarkRepository(db_session)
    await repo.advance_to(workspace_id=WORKSPACE, day=date(2026, 8, 31))
    db_session.add(
        FinancialReport(
            report_id=983877665,
            workspace_id=WORKSPACE,
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 6),
            currency="KGS",
        )
    )
    await db_session.flush()

    header_says = await FinancialReportRepository(db_session).latest_settled_date(
        workspace_id=WORKSPACE
    )
    walk_says = await repo.get(workspace_id=WORKSPACE)

    assert header_says == date(2026, 9, 6)
    assert walk_says == date(2026, 8, 31)


async def test_one_tenants_watermark_is_not_anothers(db_session: AsyncSession) -> None:
    """Each workspace's walk is paced by its own token and tracked on its own."""
    repo = SettlementWatermarkRepository(db_session)
    await repo.advance_to(workspace_id=WORKSPACE, day=date(2026, 9, 14))

    await repo.advance_to(workspace_id=OTHER_WORKSPACE, day=date(2026, 8, 3))

    assert await repo.get(workspace_id=WORKSPACE) == date(2026, 9, 14)
    assert await repo.get(workspace_id=OTHER_WORKSPACE) == date(2026, 8, 3)
