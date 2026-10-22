"""The post-deploy smoke probe, over the rows production is actually full of.

It decides whether a deploy goes red, so each of its answers has to be right: a
page that renders must pass; a page that breaks must fail, without taking the
pages after it down with it; "nothing to open" must be reported as nothing
checked rather than as a pass; and the one page whose read can write — the P&L
report over a stale settlement rollup — must be skipped, not rebuilt.

The session here is writable, unlike the probe's on production. That is what
makes the last of those provable: a rebuild would succeed here and leave rows.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke import busiest_cards, smoke
from src.core.timeutils import moscow_today
from src.modules.ab_tests.models import AbTest, AbTestVariant
from src.modules.finreports.models import (
    FinancialReport,
    LogisticsTransaction,
    SettlementDailyRollup,
)
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.heatmap.repos import SkuGroupRepository
from src.modules.monitoring.models import ProductCard, SalesFunnelDaily, StockSnapshot
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

QUIET, BUSY = 300000001, 300000002

#: One settled WB week — the whole of the workspace's P&L history, so the page
#: opens on exactly it.
WEEK_FROM, WEEK_TO = date(2026, 9, 7), date(2026, 9, 13)
REPORT_ID = 900000001


async def _workspace(session: AsyncSession, organization: Organization) -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization.id, name="Демо")
    session.add(workspace)
    await session.flush()
    return workspace


def _day(nm_id: int, *, days_ago: int, orders: int) -> SalesFunnelDaily:
    """A funnel day harvested before the money columns: its sums are NULL."""
    return SalesFunnelDaily(
        nm_id=nm_id,
        stat_date=moscow_today() - timedelta(days=days_ago),
        open_count=50,
        cart_count=5,
        order_count=orders,
        buyout_count=0,
        add_to_wishlist=0,
    )


async def _cabinet(session: AsyncSession, organization: Organization) -> Workspace:
    """A workspace with something on every main page.

    Two cards with recent orders, a stock day, one settled week with a sale in
    it, and an A/B test with one photo.
    """
    workspace = await _workspace(session, organization)
    test_id = uuid.uuid4()
    for nm_id in (QUIET, BUSY):
        session.add(ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=f"A{nm_id}"))
    session.add_all(
        [
            _day(QUIET, days_ago=2, orders=1),
            _day(BUSY, days_ago=2, orders=9),
            StockSnapshot(
                stat_date=moscow_today() - timedelta(days=1),
                nm_id=BUSY,
                warehouse_name="Коледино",
                chrt_id=1,
                quantity=5,
            ),
            FinancialReport(
                report_id=REPORT_ID,
                workspace_id=workspace.id,
                date_from=WEEK_FROM,
                date_to=WEEK_TO,
                currency="KGS",
            ),
            LogisticsTransaction(
                rrd_id=REPORT_ID,
                report_id=REPORT_ID,
                workspace_id=workspace.id,
                nm_id=BUSY,
                sa_name=f"A{BUSY}",
                supplier_oper_name="Продажа",
                rr_dt=WEEK_TO,
                currency_name="KGS",
                quantity=1,
                retail_amount=Decimal("1000"),
                ppvz_for_pay=Decimal("900"),
            ),
            AbTest(id=test_id, workspace_id=workspace.id, nm_id=BUSY, name="Главное фото"),
        ]
    )
    await session.flush()
    session.add(AbTestVariant(test_id=test_id, position=0, image_path="a.jpg", image_sha256="0"))
    await session.flush()
    return workspace


async def _open_the_week(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """What the first seller to open the week leaves behind: its rollup, built."""
    await SettlementRollup(session).ensure_fresh(
        workspace_id=workspace_id, date_from=WEEK_FROM, date_to=WEEK_TO
    )


async def _read_only_from_here(session: AsyncSession) -> None:
    """Refuse every write for the rest of the test, as the gate does on production.

    PostgreSQL lets a transaction turn read-only after it has written — only
    the other direction is refused — so the rows seeded above stay visible.
    """
    await session.execute(text("SET TRANSACTION READ ONLY"))


async def test_the_busiest_cards_render_on_rows_from_before_a_migration(
    db_session: AsyncSession, organization: Organization
) -> None:
    """What the deploy asks: do real cards open on the new code. Here, they do."""
    # Arrange
    workspace = await _workspace(db_session, organization)
    for nm_id in (QUIET, BUSY):
        db_session.add(ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=f"A{nm_id}"))
    db_session.add_all(
        [
            _day(QUIET, days_ago=2, orders=1),
            _day(BUSY, days_ago=2, orders=9),
            _day(BUSY, days_ago=40, orders=99),
        ]
    )
    await db_session.flush()

    # Act
    report = await smoke(db_session, workspace_id=workspace.id)

    # Assert
    assert report.failures == []
    assert report.cards == [BUSY, QUIET]


async def test_every_main_page_renders_on_real_rows(
    db_session: AsyncSession, organization: Organization
) -> None:
    """P&L, the heatmap and the A/B tests each open, and each on the workspace's rows.

    The row counts are the point: a page answering over an empty workspace would
    pass just as quietly, and prove nothing about the rows it never read. And it
    is read-only, as on production, where a page whose read writes is a failure.
    """
    # Arrange
    workspace = await _cabinet(db_session, organization)
    await _open_the_week(db_session, workspace.id)
    await _read_only_from_here(db_session)

    # Act
    report = await smoke(db_session, workspace_id=workspace.id)

    # Assert
    assert report.failures == []
    assert report.skipped == []
    assert report.rendered == {
        "monitoring list": 2,
        "cards": 2,
        "P&L weeks": 1,
        "P&L report": 1,
        "P&L balance": 1,
        "heatmap": 2,
        "heatmap catalogue": 2,
        "A/B list": 1,
        "A/Б test": 1,
    }


async def test_a_broken_page_fails_the_probe_and_the_pages_after_it_still_open(
    db_session: AsyncSession, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release whose code reads a column its migration never added is a failure.

    And only that page's: the error aborts the transaction, so without a
    savepoint per page every page after it would fail too and the output would
    not say which one broke.
    """

    async def read_a_column_no_migration_added(
        self: SkuGroupRepository, workspace_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str, list[int]]]:
        await self._session.execute(text("SELECT colour FROM heatmap.sku_group"))
        return []

    # Arrange
    workspace = await _cabinet(db_session, organization)
    await _open_the_week(db_session, workspace.id)
    monkeypatch.setattr(SkuGroupRepository, "list_groups", read_a_column_no_migration_added)

    # Act
    report = await smoke(db_session, workspace_id=workspace.id)

    # Assert
    assert len(report.failures) == 1
    assert report.failures[0].startswith("heatmap: ProgrammingError")
    assert "heatmap" not in report.rendered
    assert report.rendered["A/B list"] == 1
    assert report.rendered["A/Б test"] == 1


async def test_a_stale_settlement_rollup_skips_the_report_instead_of_rebuilding_it(
    db_session: AsyncSession, organization: Organization
) -> None:
    """The P&L report over a week nobody has opened yet is skipped, by name.

    Opening it would rebuild the rollup, which the probe's read-only session on
    production refuses: failing there would turn every deploy after a harvest
    red, and passing would hide that the page was never opened.
    """
    # Arrange
    workspace = await _cabinet(db_session, organization)

    # Act
    report = await smoke(db_session, workspace_id=workspace.id)

    # Assert
    rollup_rows = await db_session.scalar(
        select(func.count())
        .select_from(SettlementDailyRollup)
        .where(SettlementDailyRollup.workspace_id == workspace.id)
    )
    assert report.failures == []
    assert [skipped.split(":")[0] for skipped in report.skipped] == ["P&L report"]
    assert "P&L report" not in report.rendered
    assert rollup_rows == 0


async def test_a_cabinet_with_no_recent_orders_offers_nothing_to_open(
    db_session: AsyncSession, organization: Organization
) -> None:
    """An empty pick is "not checked", which the script turns into exit 3, not 0."""
    workspace = await _workspace(db_session, organization)
    db_session.add(ProductCard(nm_id=QUIET, workspace_id=workspace.id, vendor_code="A1"))
    db_session.add(_day(QUIET, days_ago=45, orders=3))
    await db_session.flush()

    assert await busiest_cards(db_session) == []
