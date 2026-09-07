"""Where a photo lands in the rotation, against a real database.

Position is a database fact here, not an application one: it is chosen by a
``max(position) + 1`` subquery and guarded by ``uq_ab_test_variant_test_position``,
which is **not deferrable**. Both of those are why the card's own photo takes
position 0 rather than being inserted at 1 and renumbering everything after it,
and neither can be shown by a fake.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.repos import AbTestRepository, VariantRepository
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

NM_FLOWER_DRESS = 995716075


async def _workspace(session: AsyncSession, organization_id: uuid.UUID) -> Workspace:
    """Persist a workspace, inside the tenant that owns it."""
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization_id, name="Демо")
    session.add(workspace)
    await session.flush()
    return workspace


@pytest.mark.integration
async def test_photos_are_appended_at_the_end_of_the_rotation(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Positions run 1, 2, 3 — the order the user uploaded them in.

    Rotation walks positions ascending, so a repeated or missing number would
    silently reorder or skip a photo.
    """
    workspace = await _workspace(db_session, organization.id)
    test = await AbTestRepository(db_session).create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    variants = VariantRepository(db_session)

    positions = [
        (
            await variants.add(
                test_id=test.id,
                image_path=f"{test.id}/{index}.jpg",
                image_sha256=f"{index:064d}",
                content_type="image/jpeg",
                original_filename=f"{index}.jpg",
            )
        ).position
        for index in range(3)
    ]

    assert positions == [1, 2, 3]
    assert await variants.count_for_test(test_id=test.id) == 3


@pytest.mark.integration
async def test_the_cards_own_photo_leads_the_rotation_without_renumbering_it(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The captured original takes position 0, ahead of uploads already filed.

    This cannot go lower: the reason it is 0 rather than 1 is the non-deferrable
    ``uq_ab_test_variant_test_position``, which only a real database enforces —
    and the ordering that makes 0 mean "first" is the relationship's ORDER BY,
    which only a real query applies.
    """
    workspace = await _workspace(db_session, organization.id)
    tests = AbTestRepository(db_session)
    test = await tests.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    variants = VariantRepository(db_session)
    for index in range(2):
        await variants.add(
            test_id=test.id,
            image_path=f"{test.id}/{index}.jpg",
            image_sha256=f"{index:064d}",
            content_type="image/jpeg",
            original_filename=f"{index}.jpg",
        )

    original = await variants.add_original(
        test_id=test.id,
        image_path=f"{test.id}/original.webp",
        image_sha256="f" * 64,
        content_type="image/webp",
        original_filename="Текущее фото карточки",
    )

    assert original.position == 0
    assert original.is_original is True
    # The upload cap is on uploads: the captured photo must not spend a slot.
    assert await variants.count_for_test(test_id=test.id) == 2

    db_session.expire_all()
    reloaded = await tests.get(workspace_id=workspace.id, test_id=test.id)
    assert reloaded is not None
    assert [variant.position for variant in reloaded.variants] == [0, 1, 2]
    assert [variant.is_original for variant in reloaded.variants] == [True, False, False]
