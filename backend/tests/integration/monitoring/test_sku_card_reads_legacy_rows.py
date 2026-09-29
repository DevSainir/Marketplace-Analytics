"""The SKU card, requested through the real route over rows the database really holds.

On 2026-09-29 the funnel row gained WB's own money columns, NULL for every day
harvested before them. The card's day DTO copied the row wholesale, met the
NULLs and answered 500 — on every card, for three hours, with the whole suite
green: the presenter had no test, the component tier stubs the service, and no
tier sent a request to this route over a real row.

So this one does, and the rows are the shape production is full of: harvested
before the column existed, and never touched since.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password
from src.modules.monitoring.models import PriceSnapshot, ProductCard, SalesFunnelDaily
from src.modules.organizations.models import MemberRole, Membership, Organization
from src.modules.users.models import ROLE_USER, User
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

NM_ID = 200000001
PRICED_DAY = date(2026, 9, 1)
UNPRICED_DAY = date(2026, 8, 31)


@pytest.fixture(autouse=True)
def _isolated_redis(redis_client: Any) -> None:
    """Per-test Redis: the real app checks the revocation watermark on every request."""


async def _seller(session: AsyncSession, organization: Organization) -> tuple[User, Workspace]:
    """Persist an owner of ``organization`` and one workspace of theirs."""
    user = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("a-long-enough-password"),
        email_confirmed_at=datetime.now(UTC),
        role=ROLE_USER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=MemberRole.OWNER))
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization.id, name="Кабинет")
    session.add(workspace)
    await session.flush()
    return user, workspace


def _legacy_funnel_day(stat_date: date, *, orders: int, buyouts: int) -> SalesFunnelDaily:
    """A day harvested before the money columns: order/buyout sums left NULL."""
    return SalesFunnelDaily(
        nm_id=NM_ID,
        stat_date=stat_date,
        open_count=100,
        cart_count=10,
        order_count=orders,
        buyout_count=buyouts,
        add_to_wishlist=0,
    )


async def test_the_card_opens_over_days_harvested_before_the_money_columns(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """200, with the roubles derived from the seller price — never a 500 on a NULL."""
    # Arrange
    user, workspace = await _seller(db_session, organization)
    db_session.add(
        ProductCard(nm_id=NM_ID, workspace_id=workspace.id, vendor_code="ART-1", title="Платье")
    )
    db_session.add_all(
        [
            _legacy_funnel_day(UNPRICED_DAY, orders=2, buyouts=1),
            _legacy_funnel_day(PRICED_DAY, orders=4, buyouts=2),
            PriceSnapshot(
                stat_date=PRICED_DAY,
                nm_id=NM_ID,
                seller_price=Decimal("500.00"),
                customer_price=Decimal("400.00"),
            ),
        ]
    )
    await db_session.flush()
    token, _ = create_access_token(user_id=user.id)

    # Act
    response = await api_client.get(
        f"/api/v1/monitoring/skus/{NM_ID}",
        params={"date_from": UNPRICED_DAY.isoformat(), "date_to": PRICED_DAY.isoformat()},
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(workspace.id)},
    )

    # Assert
    assert response.status_code == 200, response.text
    days = {day["stat_date"]: day for day in response.json()["funnel"]}
    assert days[PRICED_DAY.isoformat()]["order_sum"] == 2000.0
    assert days[PRICED_DAY.isoformat()]["buyout_sum"] == 1000.0
    assert days[UNPRICED_DAY.isoformat()]["order_sum"] == 0.0
