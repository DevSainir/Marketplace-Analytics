"""The nightly rating write lands only on the token's own cards, and dates nothing.

Two properties only a real database can show. The UPDATE carries
``workspace_id`` in its WHERE, so a rating WB served under one workspace's token
cannot land on a card another workspace owns. And it pins ``synced_at`` to itself:
that column says when the CATALOGUE was last synced, and the model's
``onupdate`` would otherwise stamp it on every rating write — making a stale
catalogue look fresh.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import ProductCard
from src.modules.monitoring.repos.products import ProductCardRepository

WORKSPACE = uuid.uuid4()
OTHER_WORKSPACE = uuid.uuid4()
SYNCED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def cards(db_session: AsyncSession) -> None:
    """Two cards of ours, one of a neighbour's, all synced long ago."""
    db_session.add_all(
        [
            ProductCard(nm_id=3001, workspace_id=WORKSPACE, vendor_code="OURS", synced_at=SYNCED),
            ProductCard(nm_id=3002, workspace_id=WORKSPACE, vendor_code="NEW", synced_at=SYNCED),
            ProductCard(
                nm_id=3003, workspace_id=OTHER_WORKSPACE, vendor_code="THEIRS", synced_at=SYNCED
            ),
        ]
    )
    await db_session.flush()


async def _state(session: AsyncSession) -> dict[int, tuple[Decimal | None, datetime]]:
    rows = await session.execute(
        sa.select(ProductCard.nm_id, ProductCard.feedback_rating, ProductCard.synced_at)
    )
    return {nm_id: (rating, synced) for nm_id, rating, synced in rows.all()}


async def test_ratings_land_on_the_workspace_cards_only(
    db_session: AsyncSession, cards: None
) -> None:
    await ProductCardRepository(db_session).set_feedback_ratings(
        {3001: Decimal("4.7"), 3002: None, 3003: Decimal("1.0")}, workspace_id=WORKSPACE
    )
    db_session.expire_all()

    state = await _state(db_session)

    assert state[3001][0] == Decimal("4.7")
    assert state[3002][0] is None
    # The neighbour's card was named in the batch and still refused the write.
    assert state[3003][0] is None


async def test_a_rating_write_leaves_the_catalogue_sync_time_alone(
    db_session: AsyncSession, cards: None
) -> None:
    await ProductCardRepository(db_session).set_feedback_ratings(
        {3001: Decimal("4.7")}, workspace_id=WORKSPACE
    )
    db_session.expire_all()

    state = await _state(db_session)

    assert state[3001][1] == SYNCED
