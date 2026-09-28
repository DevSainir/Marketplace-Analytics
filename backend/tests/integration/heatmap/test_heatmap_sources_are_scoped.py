"""The heatmap reads one кабинет — every source, every filter, every group.

The heatmap is the first screen that pulls EVERY article of a кабинет out of
four fact tables at once, none of which carries a workspace of its own: the
funnel, advertising, prices and stock are all keyed by the global WB article
number. So each test seeds TWO кабинеты in two organisations with facts on the
same day and asserts only one of them comes back. Real Postgres, because the
thing under test is the semijoin through ``product_card`` — a fake repository
would assert nothing about it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationError
from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.services import PnlService, SkuReportService
from src.modules.heatmap.repos import SkuGroupRepository
from src.modules.heatmap.schemas import SkuGroupWrite
from src.modules.heatmap.services import HeatmapQuery, HeatmapService, SkuGroupService
from src.modules.monitoring.contract import (
    load_ad_currencies,
    load_ad_sku_days,
    load_funnel_sku_days,
    load_price_currency,
    load_price_sku_days,
    load_stock_sku_days,
    load_workspace_catalog,
)
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    PriceSnapshot,
    ProductCard,
    SalesFunnelDaily,
    StockSnapshot,
)
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

MINE = 311111111
MINE_TOO = 311111112
THEIRS = 322222222
DAY = date(2026, 9, 23)


async def _workspace(session: AsyncSession, name: str) -> Workspace:
    """Persist a кабинет in an organisation of its own."""
    org = Organization(name=f"Орг {name}", is_primary=False)
    session.add(org)
    await session.flush()
    workspace = Workspace(organization_id=org.id, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


async def _card(session: AsyncSession, workspace: Workspace, nm_id: int, subject: str) -> None:
    """Register an article to a кабинет, with a subject, and one day of every fact."""
    session.add_all(
        [
            ProductCard(
                nm_id=nm_id,
                workspace_id=workspace.id,
                vendor_code=f"art-{nm_id}",
                subject_name=subject,
                brand="NEVA",
            ),
            SalesFunnelDaily(
                nm_id=nm_id,
                stat_date=DAY,
                open_count=100,
                cart_count=10,
                order_count=nm_id % 10,
                buyout_count=0,
                add_to_wishlist=0,
            ),
            AdvertisingStatDaily(
                nm_id=nm_id,
                stat_date=DAY,
                campaign_id=nm_id,
                app_type=1,
                views=1000,
                clicks=10,
                spend=Decimal("50.00"),
                orders=1,
                add_to_cart=1,
            ),
            PriceSnapshot(nm_id=nm_id, stat_date=DAY, seller_price=Decimal("1000.00")),
            StockSnapshot(
                nm_id=nm_id, stat_date=DAY, warehouse_name="Коледино", chrt_id=nm_id, quantity=7
            ),
        ]
    )
    await session.flush()


async def _two_tenants(session: AsyncSession) -> tuple[Workspace, Workspace]:
    """Two кабинеты: mine with two articles, theirs with one, all active on DAY."""
    mine = await _workspace(session, "Мой")
    theirs = await _workspace(session, "Чужой")
    await _card(session, mine, MINE, "Костюмы")
    await _card(session, mine, MINE_TOO, "Платья")
    await _card(session, theirs, THEIRS, "Костюмы")
    return mine, theirs


def _heatmap(session: AsyncSession) -> HeatmapService:
    """Wire the read service on the test session."""
    pnl_repo = PnlRepository(session)
    costs = CostPriceRepository(session)
    return HeatmapService(
        groups=SkuGroupRepository(session),
        pnl=PnlService(
            pnl_repo=pnl_repo, cost_repo=costs, report_repo=FinancialReportRepository(session)
        ),
        skus=SkuReportService(
            pnl_repo=pnl_repo, cost_repo=costs, exclusion_repo=SkuExclusionRepository(session)
        ),
    )


@pytest.mark.parametrize(
    "loader",
    [load_funnel_sku_days, load_ad_sku_days, load_price_sku_days, load_stock_sku_days],
    ids=lambda loader: loader.__name__,
)
async def test_every_daily_source_answers_for_one_workspace(
    db_session: AsyncSession, loader: object
) -> None:
    """A foreign article with facts on the same day never comes back."""
    mine, _ = await _two_tenants(db_session)

    rows = await loader(  # type: ignore[operator]
        db_session, workspace_id=mine.id, date_from=DAY, date_to=DAY
    )

    assert {row.nm_id for row in rows} == {MINE, MINE_TOO}


async def test_naming_a_foreign_article_cannot_widen_the_scope(db_session: AsyncSession) -> None:
    """The article narrowing is ANDed with the tenant, so a stranger's id matches nothing."""
    mine, _ = await _two_tenants(db_session)

    rows = await load_funnel_sku_days(
        db_session, workspace_id=mine.id, date_from=DAY, date_to=DAY, nm_ids=[THEIRS]
    )

    assert rows == []


async def test_the_catalogue_is_one_workspaces_cards(db_session: AsyncSession) -> None:
    """The filter options list this кабинет's articles and subjects only."""
    mine, _ = await _two_tenants(db_session)

    cards = await load_workspace_catalog(db_session, workspace_id=mine.id)

    assert {card.nm_id: card.subject_name for card in cards} == {
        MINE: "Костюмы",
        MINE_TOO: "Платья",
    }


async def test_the_grid_totals_count_only_this_workspace(db_session: AsyncSession) -> None:
    """«Итого» is this кабинет's orders; the foreign article's nine are nowhere."""
    mine, _ = await _two_tenants(db_session)
    query = HeatmapQuery(
        date_from=DAY, date_to=DAY, period="day", group_by="sku", metric="orders", metric2="spend"
    )

    grid = await _heatmap(db_session).build(db_session, workspace_id=mine.id, query=query)

    assert [row.nm_id for row in grid.rows] == [MINE_TOO, MINE]
    assert grid.totals.values == [3.0]
    assert grid.totals.values2 == [100.0]


async def test_a_category_filter_narrows_the_grid(db_session: AsyncSession) -> None:
    """«Категории» keeps the chosen subject's articles and nothing else."""
    mine, _ = await _two_tenants(db_session)
    query = HeatmapQuery(
        date_from=DAY,
        date_to=DAY,
        period="day",
        group_by="sku",
        metric="orders",
        metric2=None,
        subjects=frozenset({"Платья"}),
    )

    grid = await _heatmap(db_session).build(db_session, workspace_id=mine.id, query=query)

    assert [row.nm_id for row in grid.rows] == [MINE_TOO]


async def test_a_group_cannot_hold_another_workspaces_article(db_session: AsyncSession) -> None:
    """WB article numbers are global; «exists» is not «is yours»."""
    mine, _ = await _two_tenants(db_session)
    service = SkuGroupService(SkuGroupRepository(db_session))

    with pytest.raises(ValidationError):
        await service.create(
            db_session,
            workspace_id=mine.id,
            payload=SkuGroupWrite(name="Чужое", nm_ids=[MINE, THEIRS]),
        )


async def test_groups_are_listed_for_their_own_workspace(db_session: AsyncSession) -> None:
    """Another кабинет's groups are not options in this one's filter."""
    mine, theirs = await _two_tenants(db_session)
    service = SkuGroupService(SkuGroupRepository(db_session))
    await service.create(
        db_session, workspace_id=mine.id, payload=SkuGroupWrite(name="Мои", nm_ids=[MINE])
    )
    await service.create(
        db_session, workspace_id=theirs.id, payload=SkuGroupWrite(name="Их", nm_ids=[THEIRS])
    )

    listed = await service.list_groups(workspace_id=mine.id)

    assert [(group.name, group.nm_ids) for group in listed.items] == [("Мои", [MINE])]


async def test_a_group_cuts_the_grid_into_its_own_row(db_session: AsyncSession) -> None:
    """Cut by group: the group is one row, and the ungrouped article gets its own."""
    mine, _ = await _two_tenants(db_session)
    groups = SkuGroupService(SkuGroupRepository(db_session))
    await groups.create(
        db_session, workspace_id=mine.id, payload=SkuGroupWrite(name="Костюмы", nm_ids=[MINE])
    )
    query = HeatmapQuery(
        date_from=DAY, date_to=DAY, period="day", group_by="group", metric="stock", metric2=None
    )

    grid = await _heatmap(db_session).build(db_session, workspace_id=mine.id, query=query)

    assert sorted((row.label, row.total) for row in grid.rows) == [
        ("Без группы", 7.0),
        ("Костюмы", 7.0),
    ]
    assert grid.totals.total == 14.0


async def test_the_price_currency_is_this_workspaces_own(db_session: AsyncSession) -> None:
    """A foreign card priced in another currency on the same day must not label ours."""
    mine, _ = await _two_tenants(db_session)
    for nm_id, currency in ((MINE, "RUB"), (THEIRS, "KZT")):
        snapshot = await db_session.get(PriceSnapshot, (DAY, nm_id))
        assert snapshot is not None
        snapshot.currency = currency
    await db_session.flush()

    assert await load_price_currency(db_session, workspace_id=mine.id) == "RUB"


async def test_the_ad_currency_comes_from_this_workspaces_own_campaigns(
    db_session: AsyncSession,
) -> None:
    """Only the ledger rows of campaigns that advertised our cards; WB's bonus rows say nothing."""
    mine, _ = await _two_tenants(db_session)
    db_session.add_all(
        [
            AdvertisingWriteOffDaily(
                stat_date=DAY,
                campaign_id=MINE,
                payment_type="Баланс",
                currency="KGS",
                amount=Decimal("10"),
                write_offs=1,
            ),
            AdvertisingWriteOffDaily(
                stat_date=DAY,
                campaign_id=MINE,
                payment_type="Кэшбэк",
                currency="BYN",
                amount=Decimal("5"),
                write_offs=1,
            ),
            AdvertisingWriteOffDaily(
                stat_date=DAY,
                campaign_id=THEIRS,
                payment_type="Баланс",
                currency="RUB",
                amount=Decimal("99"),
                write_offs=1,
            ),
        ]
    )
    await db_session.flush()

    currencies = await load_ad_currencies(
        db_session, workspace_id=mine.id, date_from=DAY, date_to=DAY
    )

    assert currencies == ["KGS"]
