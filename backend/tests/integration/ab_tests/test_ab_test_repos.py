"""A/Б-test reads and writes against a real database.

These cannot go lower. The search predicate is SQL — four `OR`ed matches, one of
them a cast of a bigint to text — and a fake repository would assert nothing but
its own `in` operator. The same goes for the composite-key upsert of attributed
days and for the append-at-the-end position of a new photo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AbTestStatus
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    VariantRepository,
    VariantStatRepository,
)
from src.modules.ab_tests.services.attribution import AttributedDay
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

NM_FLOWER_DRESS = 995716075
NM_PLAIN_SUIT = 1948347102


async def _workspace(
    session: AsyncSession, organization_id: uuid.UUID, name: str = "Демо"
) -> Workspace:
    """Persist a workspace, inside the tenant that owns it."""
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization_id, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


async def _seed(session: AsyncSession, workspace: Workspace) -> AbTestRepository:
    """Create the three tests every search case below searches over."""
    repo = AbTestRepository(session)
    await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест главного фото",
        impression_budget=10_000,
    )
    await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_PLAIN_SUIT,
        vendor_code="ДЕТ_КОСТЮМ_ДВОЙКА_ОДНОТОН",
        name="Костюм: фон против модели",
        impression_budget=10_000,
    )
    paused = await repo.create(
        workspace_id=workspace.id,
        nm_id=953770957,
        vendor_code="ДЖН_КОСТЮМ_ДЖИНСА",
        name="Джинса, крупный план",
        impression_budget=25_000,
    )
    await repo.set_status(test=paused, status=AbTestStatus.PAUSED)
    return repo


# --------------------------------------------------------------------------- #
# Search — every field the list shows
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_search_matches_the_test_name(
    db_session: AsyncSession, organization: Organization
) -> None:
    """The needle finds a test by its title, case-insensitively."""
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    found = await repo.search(workspace_id=workspace.id, query="главного")

    assert [test.name for test in found] == ["Тест главного фото"]


@pytest.mark.integration
async def test_search_matches_the_sellers_article(
    db_session: AsyncSession, organization: Organization
) -> None:
    """Артикул продавца is searchable — it is what the team actually types."""
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    found = await repo.search(workspace_id=workspace.id, query="ДЖИНСА")

    assert [test.vendor_code for test in found] == ["ДЖН_КОСТЮМ_ДЖИНСА"]


@pytest.mark.integration
async def test_search_matches_a_partial_wb_article(
    db_session: AsyncSession, organization: Organization
) -> None:
    """A fragment of the nmID matches, because users paste partial articles.

    The column is a bigint, so this only works if the predicate casts it to
    text — an `=` comparison would silently return nothing for a fragment.
    """
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    found = await repo.search(workspace_id=workspace.id, query="57160")

    assert [test.nm_id for test in found] == [NM_FLOWER_DRESS]


@pytest.mark.integration
async def test_search_matches_the_status(
    db_session: AsyncSession, organization: Organization
) -> None:
    """Typing a status filters by it, so one box covers the whole row."""
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    found = await repo.search(workspace_id=workspace.id, query="paused")

    assert [test.status for test in found] == [AbTestStatus.PAUSED.value]


@pytest.mark.integration
async def test_a_blank_needle_returns_everything_newest_first(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """No search is not an empty search."""
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    assert len(await repo.search(workspace_id=workspace.id, query="  ")) == 3
    assert len(await repo.search(workspace_id=workspace.id, query=None)) == 3


@pytest.mark.integration
async def test_search_never_crosses_workspaces(
    db_session: AsyncSession, organization: Organization
) -> None:
    """A needle that matches a neighbour's test still returns nothing.

    Tenancy is in the predicate, not in a later filter — a test rewrites a live
    card, so a leak here changes someone else's storefront.
    """
    mine = await _workspace(db_session, organization.id, "Демо")
    theirs = await _workspace(db_session, organization.id, "Марат")
    await _seed(db_session, theirs)

    assert await AbTestRepository(db_session).search(workspace_id=mine.id, query="ЦВЕТОЧЕК") == []


# --------------------------------------------------------------------------- #
# Variants, exposures and attributed days
# --------------------------------------------------------------------------- #


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
        impression_budget=10_000,
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
async def test_a_days_metrics_are_overwritten_by_a_later_reading(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Re-attributing a day updates it rather than duplicating it.

    WB restates recent advertising days as conversions settle, so every pass
    re-reads the last month; without the upsert the same day would accumulate.
    """
    workspace = await _workspace(db_session, organization.id)
    tests = AbTestRepository(db_session)
    test = await tests.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
        impression_budget=10_000,
    )
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    stats = VariantStatRepository(db_session)
    day = date(2026, 8, 2)

    await stats.upsert_days(
        test_id=test.id,
        days=[AttributedDay(variant.id, day, 1_000, 90, 8, 3, Decimal("1500.00"))],
    )
    await stats.upsert_days(
        test_id=test.id,
        days=[AttributedDay(variant.id, day, 1_050, 95, 9, 5, Decimal("1600.00"))],
    )

    rows = await stats.days_for_test(test_id=test.id)
    assert len(rows) == 1
    assert (rows[0].views, rows[0].orders) == (1_050, 5)
    assert await stats.impressions_for_variant(variant_id=variant.id) == 1_050


@pytest.mark.integration
async def test_an_exposure_is_closed_when_the_next_photo_goes_up(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Closing writes an end to the open window and leaves earlier ones alone.

    The windows are what attribution reads; an unclosed one would keep claiming
    every day after the swap for the photo that came off.
    """
    workspace = await _workspace(db_session, organization.id)
    test = await AbTestRepository(db_session).create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
        impression_budget=10_000,
    )
    variants = VariantRepository(db_session)
    first = await variants.add(
        test_id=test.id,
        image_path="1.jpg",
        image_sha256="1" * 64,
        content_type="image/jpeg",
        original_filename="1.jpg",
    )
    second = await variants.add(
        test_id=test.id,
        image_path="2.jpg",
        image_sha256="2" * 64,
        content_type="image/jpeg",
        original_filename="2.jpg",
    )
    exposures = ExposureRepository(db_session)

    await exposures.open(
        test_id=test.id, variant_id=first.id, activated_at=datetime(2026, 8, 1, tzinfo=UTC)
    )
    await exposures.close_open(test_id=test.id, deactivated_at=datetime(2026, 8, 5, tzinfo=UTC))
    await exposures.open(
        test_id=test.id, variant_id=second.id, activated_at=datetime(2026, 8, 5, tzinfo=UTC)
    )

    windows = await exposures.windows_for_test(test_id=test.id)
    assert [w.variant_id for w in windows] == [first.id, second.id]
    assert windows[0].deactivated_at is not None
    assert windows[1].deactivated_at is None


@pytest.mark.integration
async def test_deleting_a_test_takes_its_photos_and_days_with_it(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The cascade is real, so a deleted test leaves no orphan metrics behind."""
    workspace = await _workspace(db_session, organization.id)
    tests = AbTestRepository(db_session)
    test = await tests.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
        impression_budget=10_000,
    )
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    stats = VariantStatRepository(db_session)
    await stats.upsert_days(
        test_id=test.id,
        days=[AttributedDay(variant.id, date(2026, 8, 2), 10, 1, 0, 0, Decimal("0.00"))],
    )

    assert await tests.delete(workspace_id=workspace.id, test_id=test.id) is True

    assert await stats.days_for_test(test_id=test.id) == []
    assert await tests.get(workspace_id=workspace.id, test_id=test.id) is None
