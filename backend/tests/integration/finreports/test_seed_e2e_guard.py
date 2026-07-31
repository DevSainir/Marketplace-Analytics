"""The e2e fixture seeder must never inject its demo week into real data.

Regression guard for a real incident: a stray local ``make seed-e2e`` ran
``scripts.seed_e2e_fixtures`` against the *dev* database (the script uses the
app's default session, so it follows ``.env``), and its fixture week — report
990000001, a fake RUB «Логистика»+«Штраф» on a real SKU — landed in «Демо».
Because the report is settlement-date-based, that fake week then skewed every
date window covering it, and its stray RUB row poisoned the currency selection.

``_ensure_finreports_week`` now refuses when the database already holds real
settlement rows. These tests pin both directions of that guard.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_e2e_fixtures import _FIXTURE_REPORT_ID, _ensure_finreports_week
from src.modules.finreports.models import FinancialReport, LogisticsTransaction

pytestmark = pytest.mark.integration

_WS = uuid.UUID("019f657a-0000-7000-8000-0000000e2e00")


async def test_the_fixture_week_is_refused_when_real_settlements_exist(
    db_session: AsyncSession,
) -> None:
    """One real row is enough — the seeder must not touch a populated database."""
    db_session.add(
        LogisticsTransaction(
            rrd_id=700_000_001,
            report_id=700_000_000,  # a real, non-fixture report
            workspace_id=_WS,
            nm_id=12345,
            supplier_oper_name="Продажа",
            rr_dt=date(2026, 7, 1),
            currency_name="KGS",
            ppvz_for_pay=100,
        )
    )
    await db_session.flush()

    created = await _ensure_finreports_week(db_session, _WS)

    assert created is False
    # And it inserted nothing — no fixture report, no fixture rows.
    assert await db_session.get(FinancialReport, _FIXTURE_REPORT_ID) is None
    assert await db_session.get(LogisticsTransaction, 990_000_101) is None


async def test_the_fixture_week_seeds_a_fresh_database(db_session: AsyncSession) -> None:
    """On an empty settlement table (the real e2e case) it still seeds normally."""
    created = await _ensure_finreports_week(db_session, _WS)
    await db_session.flush()  # the real caller commits; here we just persist

    assert created is True
    assert await db_session.get(FinancialReport, _FIXTURE_REPORT_ID) is not None
    assert await db_session.get(LogisticsTransaction, 990_000_101) is not None
