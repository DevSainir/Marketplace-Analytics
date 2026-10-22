"""The finishing touches: heatmap groups and norms, and the P&L freshness line.

Neither is data a page needs to render, but both are what a seller who has used
the product for a while would have set up, and the screens look half-configured
without them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo.catalogue import SKUS
from src.core.redis import get_redis
from src.modules.finreports.constants import FRESHNESS_RECORD_TTL_SECONDS
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
    RedisFreshnessRecordStore,
)
from src.modules.heatmap.models import SkuGroup, SkuGroupItem, SkuNorm

#: Groups by what the articles are, the way a seller would cut the catalogue.
_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("Брюки", (SKUS[0].nm_id, SKUS[1].nm_id, SKUS[4].nm_id)),
    ("Худи и футболки", (SKUS[3].nm_id, SKUS[5].nm_id)),
    ("Костюмы", (SKUS[2].nm_id,)),
)

#: Daily order targets: a cell below its norm is what the heatmap highlights.
_ORDER_NORMS: tuple[tuple[int, float], ...] = (
    (SKUS[0].nm_id, 32.0),
    (SKUS[3].nm_id, 30.0),
    (SKUS[5].nm_id, 52.0),
)


async def seed_heatmap(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Write the article groups and order norms. Returns rows written."""
    written = 0
    for name, members in _GROUPS:
        group = SkuGroup(workspace_id=workspace_id, name=name)
        session.add(group)
        await session.flush()
        session.add_all(
            SkuGroupItem(group_id=group.id, nm_id=nm_id, workspace_id=workspace_id)
            for nm_id in members
        )
        written += 1 + len(members)
    session.add_all(
        SkuNorm(workspace_id=workspace_id, nm_id=nm_id, metric="orders", value=value)
        for nm_id, value in _ORDER_NORMS
    )
    await session.flush()
    return written + len(_ORDER_NORMS)


async def mark_settlement_fresh(workspace_id: uuid.UUID) -> None:
    """Record that the settlement is up to date, as the harvest would after checking WB.

    Without it the P&L page says, correctly, that nobody has asked WB yet. The
    record expires on its own; past a day the page turns that line amber again.
    """
    store = RedisFreshnessRecordStore(get_redis(), ttl_seconds=FRESHNESS_RECORD_TTL_SECONDS)
    await store.put(workspace_id, FreshnessVerdict(FreshnessOutcome.UP_TO_DATE, datetime.now(UTC)))
