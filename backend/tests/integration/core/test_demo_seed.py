"""The demo seed, against a real database: what it refuses, and what it shows.

The seed empties every table before it writes, so its guard is the part that
matters most, and only a real database can show the guard reads the right
tables. The other half is the point of the demo: once seeded, the P&L for the
newest week has no gaps — every article costed, orders and advertising known —
because a demo page full of «unknown» caveats demonstrates nothing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import settlement, simulation
from scripts.seed_demo.shop import populate_workspace
from scripts.seed_demo.tenancy import (
    NotADemoDatabaseError,
    assert_demo_database,
    create_identity,
)
from src.core.config import settings
from src.modules.finreports.repos import CostPriceRepository, PnlRepository, SkuExclusionRepository
from src.modules.finreports.services.pnl import SkuReportService
from src.modules.monitoring import contract as monitoring
from src.modules.monitoring.models import ProductCard
from src.modules.users.models import User

pytestmark = pytest.mark.integration

_TODAY = date(2026, 10, 22)


async def test_the_seed_refuses_a_database_with_someone_elses_account(
    db_session: AsyncSession,
) -> None:
    """One account that is not the demo's is enough to refuse."""
    db_session.add(User(email="someone@example.com", hashed_password="x"))
    await db_session.flush()

    with pytest.raises(NotADemoDatabaseError, match="1 accounts"):
        await assert_demo_database(db_session)


async def test_the_seed_refuses_a_database_with_a_real_catalogue(
    db_session: AsyncSession,
) -> None:
    """A card outside the demo's id range is real use, whoever owns it."""
    db_session.add(ProductCard(nm_id=123_456_789, vendor_code="REAL-1", title="Real"))
    await db_session.flush()

    with pytest.raises(NotADemoDatabaseError, match="1 catalogue cards"):
        await assert_demo_database(db_session)


async def test_the_seed_accepts_a_freshly_migrated_database(db_session: AsyncSession) -> None:
    """Nothing but the schema: the guard lets the seed through."""
    await assert_demo_database(db_session)


async def test_the_seeded_week_has_no_gaps_on_the_pnl(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Newest week: every article sold and costed, and no «unknown» caveat."""
    monkeypatch.setattr(settings, "ab_tests_media_dir", str(tmp_path))
    # Five weeks of history and two reports cover the newest week; the demo's
    # full four months take three times as long to write and prove nothing more.
    monkeypatch.setattr(simulation, "HISTORY_DAYS", 35)
    monkeypatch.setattr(settlement, "REPORTS", 2)
    workspace_id = await create_identity(db_session)
    await populate_workspace(db_session, workspace_id, _TODAY)
    week = settlement.periods(_TODAY)[0]
    window = {"workspace_id": workspace_id, "date_from": week.date_from, "date_to": week.date_to}
    service = SkuReportService(
        pnl_repo=PnlRepository(db_session),
        cost_repo=CostPriceRepository(db_session),
        exclusion_repo=SkuExclusionRepository(db_session),
    )

    report = await service.get_report(
        **window,
        orders=await monitoring.load_orders_by_nm(db_session, **window),
        buyouts=await monitoring.load_buyouts_by_nm(db_session, **window),
        ad_spend=await monitoring.load_ad_spend_by_nm(db_session, **window),
        funnel_span=await monitoring.funnel_coverage(db_session, **window),
        ad_span=await monitoring.ad_coverage(db_session, **window),
        ad_bonus=await monitoring.load_ad_bonus_by_nm(db_session, **window),
        bonus_span=await monitoring.ad_bonus_coverage(db_session, **window),
        unknown_funding=await monitoring.ad_bonus_unknown_types(db_session, **window),
    )

    assert report.notes == []
    assert len(report.rows) == 6
    assert all(row.sold_units > 0 for row in report.rows)
    assert all(row.cogs is not None and row.net_profit is not None for row in report.rows)
