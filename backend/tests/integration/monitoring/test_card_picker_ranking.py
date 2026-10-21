"""How the A/B test article picker orders the catalogue it opens with.

This is SQL — two grouped subqueries joined to a page of cards and three sort
keys — so a fake repository would assert nothing but its own `sorted()`. The
window is relative to «today» in Moscow, which is the other reason it belongs
here: the loader reads the clock, and a test that pinned a date would pass on
data the loader can no longer see.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.monitoring.contract import search_workspace_cards
from src.modules.monitoring.models import AdvertisingStatDaily, ProductCard, SalesFunnelDaily
from src.modules.monitoring.services.cards import RANKING_DAYS
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

#: Named so the expected order is readable in the assertions rather than being a
#: list of nine-digit numbers nobody can hold in their head.
QUIET = 100000001
SELLER = 100000002
ADVERTISED = 100000003


async def _workspace(session: AsyncSession, name: str) -> Workspace:
    """Persist a workspace in its own organisation."""
    org = Organization(name=f"Орг {name}", is_primary=False)
    session.add(org)
    await session.flush()
    workspace = Workspace(id=uuid.uuid4(), organization_id=org.id, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


async def _card(session: AsyncSession, workspace: Workspace, nm_id: int, code: str) -> None:
    """Register one catalogue card to a workspace."""
    session.add(
        ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=code, title="Платье")
    )
    await session.flush()


async def _orders(session: AsyncSession, nm_id: int, *, days_ago: int, orders: int) -> None:
    """One day of funnel history, dated relative to today."""
    session.add(
        SalesFunnelDaily(
            nm_id=nm_id,
            stat_date=moscow_today() - timedelta(days=days_ago),
            open_count=0,
            cart_count=0,
            order_count=orders,
            buyout_count=0,
            add_to_wishlist=0,
        )
    )
    await session.flush()


async def _ads(session: AsyncSession, nm_id: int, *, days_ago: int, views: int) -> None:
    """One day of advertising, dated relative to today."""
    session.add(
        AdvertisingStatDaily(
            nm_id=nm_id,
            stat_date=moscow_today() - timedelta(days=days_ago),
            campaign_id=1,
            app_type=1,
            views=views,
            clicks=0,
            add_to_cart=0,
            spend=Decimal("10.00"),
            orders=0,
        )
    )
    await session.flush()


async def test_advertised_cards_come_first_then_the_best_sellers(
    db_session: AsyncSession,
) -> None:
    """The order is what the picker opens with, so it has to be the useful one.

    Alphabetically this is exactly backwards — `А-`, `Б-`, `Я-` — which is what
    the vendor-code ordering used to serve. A rotation on «по показам» only
    advances while the card is advertised, so an unadvertised card belongs below
    every advertised one however well it sells.
    """
    workspace = await _workspace(db_session, "Мой")
    await _card(db_session, workspace, QUIET, "А-тихий")
    await _card(db_session, workspace, SELLER, "Б-ходовой")
    await _card(db_session, workspace, ADVERTISED, "Я-рекламируемый")
    await _orders(db_session, SELLER, days_ago=1, orders=90)
    await _orders(db_session, ADVERTISED, days_ago=1, orders=5)
    await _ads(db_session, ADVERTISED, days_ago=1, views=1000)

    cards = await search_workspace_cards(db_session, workspace_id=workspace.id, needle="")

    assert [card.nm_id for card in cards] == [ADVERTISED, SELLER, QUIET]
    assert [(card.orders_7d, card.has_ads) for card in cards] == [
        (5, True),
        (90, False),
        (0, False),
    ]


async def test_only_the_last_week_counts_towards_the_ranking(db_session: AsyncSession) -> None:
    """A card that sold well a month ago is not a card worth testing today."""
    workspace = await _workspace(db_session, "Мой")
    await _card(db_session, workspace, QUIET, "А-тихий")
    await _card(db_session, workspace, SELLER, "Б-ходовой")
    # Just outside the window on one side, just inside on the other.
    await _orders(db_session, QUIET, days_ago=RANKING_DAYS + 1, orders=500)
    await _orders(db_session, SELLER, days_ago=RANKING_DAYS - 1, orders=3)

    cards = await search_workspace_cards(db_session, workspace_id=workspace.id, needle="")

    assert [card.nm_id for card in cards] == [SELLER, QUIET]
    assert [card.orders_7d for card in cards] == [3, 0]


async def test_an_advertising_row_that_served_nothing_is_not_advertising(
    db_session: AsyncSession,
) -> None:
    """WB writes a zero-impression row for a campaign that never ran.

    Counting it would float every card ever attached to a paused campaign above
    the ones actually selling — the opposite of what the ranking is for.
    """
    workspace = await _workspace(db_session, "Мой")
    await _card(db_session, workspace, QUIET, "А-тихий")
    await _card(db_session, workspace, SELLER, "Б-ходовой")
    await _ads(db_session, QUIET, days_ago=1, views=0)
    await _orders(db_session, SELLER, days_ago=1, orders=4)

    cards = await search_workspace_cards(db_session, workspace_id=workspace.id, needle="")

    assert [card.nm_id for card in cards] == [SELLER, QUIET]
    assert [card.has_ads for card in cards] == [False, False]


async def test_another_tenants_sales_never_rank_this_tenants_cards(
    db_session: AsyncSession,
) -> None:
    """The aggregates are scoped, not just the page of cards they are joined to.

    ``sales_funnel_daily`` is keyed by ``nm_id`` alone, so two workspaces holding
    the same article share its rows. The ranking must still read one tenant's.
    """
    mine = await _workspace(db_session, "Мой")
    theirs = await _workspace(db_session, "Чужой")
    await _card(db_session, mine, QUIET, "А-тихий")
    await _card(db_session, theirs, SELLER, "Б-чужой")
    await _orders(db_session, SELLER, days_ago=1, orders=900)
    await _ads(db_session, SELLER, days_ago=1, views=9000)

    cards = await search_workspace_cards(db_session, workspace_id=mine.id, needle="")

    assert [(card.nm_id, card.orders_7d, card.has_ads) for card in cards] == [(QUIET, 0, False)]
