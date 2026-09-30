"""The heatmap's hand-set norms against real Postgres.

Real, because two things under test live in the database: the upsert on the
``(workspace, article, metric)`` constraint, and that a norm is written,
read and cleared for ONE кабинет only.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationError
from src.modules.heatmap.repos import SkuNormRepository
from src.modules.heatmap.services import SkuNormService
from src.modules.monitoring.models import ProductCard
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

MINE = 311111111
THEIRS = 322222222


async def _workspace_with_card(session: AsyncSession, name: str, nm_id: int) -> Workspace:
    """Persist a кабинет in an organisation of its own, owning one article."""
    org = Organization(name=f"Орг {name}", is_primary=False)
    session.add(org)
    await session.flush()
    workspace = Workspace(organization_id=org.id, name=name)
    session.add(workspace)
    await session.flush()
    session.add(ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=f"art-{nm_id}"))
    await session.flush()
    return workspace


async def test_setting_a_norm_twice_keeps_the_last_value(db_session: AsyncSession) -> None:
    """One norm per article and metric: a second set replaces, never stacks."""
    mine = await _workspace_with_card(db_session, "Мой", MINE)
    service = SkuNormService(SkuNormRepository(db_session))

    await service.set_norm(db_session, workspace_id=mine.id, nm_id=MINE, metric="orders", value=50)
    await service.set_norm(db_session, workspace_id=mine.id, nm_id=MINE, metric="orders", value=80)
    await service.set_norm(db_session, workspace_id=mine.id, nm_id=MINE, metric="ctr", value=2.5)

    listed = await service.list_norms(workspace_id=mine.id)
    assert [(n.nm_id, n.metric, n.value) for n in listed.items] == [
        (MINE, "ctr", 2.5),
        (MINE, "orders", 80.0),
    ]


async def test_a_norm_cannot_be_set_on_another_workspaces_article(
    db_session: AsyncSession,
) -> None:
    """«This article exists» is not «this article is yours»."""
    mine = await _workspace_with_card(db_session, "Мой", MINE)
    await _workspace_with_card(db_session, "Чужой", THEIRS)
    service = SkuNormService(SkuNormRepository(db_session))

    with pytest.raises(ValidationError):
        await service.set_norm(
            db_session, workspace_id=mine.id, nm_id=THEIRS, metric="orders", value=5
        )


async def test_norms_are_listed_and_cleared_for_their_own_workspace(
    db_session: AsyncSession,
) -> None:
    """Another кабинет's norm is neither listed nor cleared, even when named."""
    mine = await _workspace_with_card(db_session, "Мой", MINE)
    theirs = await _workspace_with_card(db_session, "Чужой", THEIRS)
    service = SkuNormService(SkuNormRepository(db_session))
    await service.set_norm(db_session, workspace_id=mine.id, nm_id=MINE, metric="orders", value=1)
    await service.set_norm(
        db_session, workspace_id=theirs.id, nm_id=THEIRS, metric="orders", value=99
    )

    await service.clear_norm(workspace_id=mine.id, nm_id=MINE, metric="orders")
    await service.clear_norm(workspace_id=mine.id, nm_id=THEIRS, metric="orders")

    assert (await service.list_norms(workspace_id=mine.id)).items == []
    kept = (await service.list_norms(workspace_id=theirs.id)).items
    assert [(n.nm_id, n.value) for n in kept] == [(THEIRS, 99.0)]
