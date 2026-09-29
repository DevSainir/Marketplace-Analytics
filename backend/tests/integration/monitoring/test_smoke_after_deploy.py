"""The post-deploy smoke probe, over the rows production is actually full of.

It decides whether a release is rolled back, so both of its answers have to be
right: a card that renders must pass, and "nothing to open" must be reported as
nothing checked rather than as a pass.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke_after_deploy import busiest_cards, smoke
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import ProductCard, SalesFunnelDaily
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

QUIET, BUSY = 300000001, 300000002


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
    cards, failures = await smoke(db_session, workspace_id=workspace.id)

    # Assert
    assert failures == []
    assert cards == [BUSY, QUIET]


async def test_a_cabinet_with_no_recent_orders_offers_nothing_to_open(
    db_session: AsyncSession, organization: Organization
) -> None:
    """An empty pick is "not checked", which the script turns into exit 3, not 0."""
    workspace = await _workspace(db_session, organization)
    db_session.add(ProductCard(nm_id=QUIET, workspace_id=workspace.id, vendor_code="A1"))
    db_session.add(_day(QUIET, days_ago=45, orders=3))
    await db_session.flush()

    assert await busiest_cards(db_session) == []
