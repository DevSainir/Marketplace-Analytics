"""The top-up pass must never overwrite a customer price that is already there.

The rule is not in Python. ``fill_missing_customer_price`` carries
``customer_price IS NULL`` inside the UPDATE precisely so that a harvest landing
between "read the gaps" and "write them" cannot be clobbered by a stale answer —
a loop that checked first would still have that window. Only a real database can
show the predicate doing its job.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import ProductCard
from src.modules.monitoring.models.prices import PriceSnapshot
from src.modules.monitoring.repos.prices import PriceRepository

WORKSPACE = uuid.uuid4()
OTHER_WORKSPACE = uuid.uuid4()
DAY = date(2026, 7, 2)


@pytest.fixture
async def snapshot(db_session: AsyncSession) -> None:
    """One day's snapshot: a priced SKU, an unpriced one, and a neighbour's."""
    db_session.add_all(
        [
            ProductCard(nm_id=2001, workspace_id=WORKSPACE, vendor_code="PRICED"),
            ProductCard(nm_id=2002, workspace_id=WORKSPACE, vendor_code="EMPTY"),
            ProductCard(nm_id=2003, workspace_id=OTHER_WORKSPACE, vendor_code="THEIRS"),
        ]
    )
    db_session.add_all(
        [
            PriceSnapshot(
                stat_date=DAY,
                nm_id=2001,
                seller_price=500,
                customer_price=430,
                customer_source="storefront",
            ),
            PriceSnapshot(stat_date=DAY, nm_id=2002, seller_price=700, customer_price=None),
            PriceSnapshot(stat_date=DAY, nm_id=2003, seller_price=900, customer_price=None),
        ]
    )
    await db_session.flush()


async def test_a_price_that_is_already_there_survives_the_top_up(
    db_session: AsyncSession, snapshot: None
) -> None:
    """The UPDATE refuses the row, reports it, and leaves every column alone."""
    repo = PriceRepository(db_session)

    filled = await repo.fill_missing_customer_price(
        stat_date=DAY, nm_id=2001, customer_price=999, spp=40, source="orders"
    )

    assert filled is False
    row = (
        await db_session.execute(sa.select(PriceSnapshot).where(PriceSnapshot.nm_id == 2001))
    ).scalar_one()
    assert float(row.customer_price) == 430.0
    assert row.customer_source == "storefront"
    assert row.customer_spp is None


async def test_an_empty_price_is_filled_and_labelled(
    db_session: AsyncSession, snapshot: None
) -> None:
    """The gap the pass exists for: price, СПП and source all land together."""
    repo = PriceRepository(db_session)

    filled = await repo.fill_missing_customer_price(
        stat_date=DAY, nm_id=2002, customer_price=610, spp=12, source="orders"
    )

    assert filled is True
    row = (
        await db_session.execute(sa.select(PriceSnapshot).where(PriceSnapshot.nm_id == 2002))
    ).scalar_one()
    assert float(row.customer_price) == 610.0
    assert float(row.customer_spp) == 12.0
    assert row.customer_source == "orders"
    # The seller side is not this pass's business and must be untouched.
    assert float(row.seller_price) == 700.0


async def test_the_gap_list_is_scoped_to_the_workspace(
    db_session: AsyncSession, snapshot: None
) -> None:
    """A neighbour's unpriced SKU is not this workspace's gap to fill."""
    repo = PriceRepository(db_session)

    missing = await repo.skus_missing_customer_price(workspace_id=WORKSPACE, stat_date=DAY)

    assert missing == [2002]
