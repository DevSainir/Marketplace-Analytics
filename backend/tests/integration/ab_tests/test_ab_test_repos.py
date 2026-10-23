"""Tests, their photos and their turns, against a real database.

These cannot go lower. The search predicate is SQL — four `OR`ed matches, one of
them a cast of a bigint to text — and a fake repository would assert nothing but
its own `in` operator. The same goes for the tenancy guard the image route now
carries as a JOIN, and for a cascade that only a foreign key performs.

What those turns MEASURED lives in test_measurement_repos.py, and the rotation's
ordering in test_rotation_order.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AbTestStatus, TriggerMode
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.collection import Counters
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

NM_FLOWER_DRESS = 995716075
NM_PLAIN_SUIT = 1948347102


async def _workspace(
    session: AsyncSession, organization_id: uuid.UUID, name: str = "Demo"
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
        vendor_code="KID_DRESS_FLORAL",
        name="Main photo test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_PLAIN_SUIT,
        vendor_code="KID_SUIT_TWOPIECE_PLAIN",
        name="Suit: plain backdrop vs model",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    paused = await repo.create(
        workspace_id=workspace.id,
        nm_id=953770957,
        vendor_code="JNS_SUIT_DENIM",
        name="Fabric close-up",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=25_000,
        slot_minutes=60,
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

    found = await repo.search(workspace_id=workspace.id, query="main")

    assert [test.name for test in found] == ["Main photo test"]


@pytest.mark.integration
async def test_search_matches_the_sellers_article(
    db_session: AsyncSession, organization: Organization
) -> None:
    """The vendor code is searchable.

    It is what the team actually types.
    """
    workspace = await _workspace(db_session, organization.id)
    repo = await _seed(db_session, workspace)

    found = await repo.search(workspace_id=workspace.id, query="DENIM")

    assert [test.vendor_code for test in found] == ["JNS_SUIT_DENIM"]


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
    mine = await _workspace(db_session, organization.id, "Demo")
    theirs = await _workspace(db_session, organization.id, "Marat")
    await _seed(db_session, theirs)

    assert await AbTestRepository(db_session).search(workspace_id=mine.id, query="FLORAL") == []


# --------------------------------------------------------------------------- #
# Variants, exposures and attributed days
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_an_exposure_is_closed_when_the_next_photo_goes_up(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Closing ends the open exposure and leaves the earlier ones alone.

    The open exposure is what the time trigger reads, so an unclosed one would
    keep reporting the outgoing photo's install time and the rotation would
    either stall or fire immediately, depending on how long ago that was.
    """
    workspace = await _workspace(db_session, organization.id)
    test = await AbTestRepository(db_session).create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
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

    # `active_since` is what the time trigger measures against, so what matters
    # is that it now reports the SECOND photo's install rather than the first's.
    assert await exposures.active_since(test_id=test.id) == datetime(2026, 8, 5, tzinfo=UTC)
    assert await exposures.count_for_variant(variant_id=first.id) == 1
    assert await exposures.count_for_variant(variant_id=second.id) == 1


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
        vendor_code="KID_DRESS_FLORAL",
        name="Test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    windows = WindowRepository(db_session)
    await windows.append(
        test_id=test.id,
        variant_id=variant.id,
        campaign_id=97455930,
        window_start=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        window_end=datetime(2026, 9, 4, 12, 5, tzinfo=UTC),
        counters=Counters(views=10, clicks=1),
    )

    assert await tests.delete(workspace_id=workspace.id, test_id=test.id) is True

    assert await windows.windows_for_test(test_id=test.id) == []
    assert await tests.get(workspace_id=workspace.id, test_id=test.id) is None


@pytest.mark.integration
async def test_a_running_test_can_be_deleted_with_its_photo_still_on_the_card(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The two tables point at each other, and the delete has to survive it.

    ``ab_test.active_variant_id`` references a variant `ON DELETE SET NULL`
    while ``ab_test_variant.test_id`` references the test `ON DELETE CASCADE`.
    The cycle only closes once a test has actually started, so every earlier
    delete test — all of which used drafts — passed without touching it.
    """
    workspace = await _workspace(db_session, organization.id)
    tests = AbTestRepository(db_session)
    test = await tests.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Running",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    await tests.set_active_variant(test=test, variant_id=variant.id)
    await ExposureRepository(db_session).open(
        test_id=test.id, variant_id=variant.id, activated_at=datetime(2026, 9, 4, tzinfo=UTC)
    )

    assert await tests.delete(workspace_id=workspace.id, test_id=test.id) is True

    assert await tests.get(workspace_id=workspace.id, test_id=test.id) is None


@pytest.mark.integration
async def test_a_stopped_test_records_when_and_a_resumed_one_forgets(
    db_session: AsyncSession, organization: Organization
) -> None:
    """The "Stopped" time has to survive a pause and vanish on a resume.

    ``finished_at`` answers this only for a test that ended, and the case the
    page actually asks about is the paused one. A ``stopped_at`` left behind by
    a resume would go on answering "up since 14:05" for a test that is running.
    """
    workspace = await _workspace(db_session, organization.id)
    repo = AbTestRepository(db_session)
    test = await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Main photo test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    paused_at = datetime(2026, 9, 9, 14, 5, tzinfo=UTC)

    await repo.set_status(test=test, status=AbTestStatus.PAUSED, stopped_at=paused_at)
    assert test.stopped_at == paused_at

    await repo.set_status(test=test, status=AbTestStatus.RUNNING)
    assert test.stopped_at is None


@pytest.mark.integration
async def test_the_rotations_own_pause_records_when_it_happened(
    db_session: AsyncSession, organization: Organization
) -> None:
    """A test paused by the advertising is as stopped as one paused by hand."""
    workspace = await _workspace(db_session, organization.id)
    repo = AbTestRepository(db_session)
    test = await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Main photo test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    stopped = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)

    await repo.pause_for_ads(test=test, at=stopped)
    assert (test.stopped_at, test.paused_by_ads) == (stopped, True)

    await repo.resume_after_ads(test=test)
    assert (test.stopped_at, test.paused_by_ads) == (None, False)


@pytest.mark.integration
async def test_a_hand_made_pause_is_never_lifted_by_the_advertising(
    db_session: AsyncSession, organization: Organization
) -> None:
    """Starting an ads-paused test by hand ends the rotation's claim on it.

    The flag used to survive that start, so the seller's own pause afterwards
    still carried it and the sweep lifted it the moment a campaign served.
    """
    workspace = await _workspace(db_session, organization.id)
    repo = AbTestRepository(db_session)
    test = await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Main photo test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    await repo.pause_for_ads(test=test, at=datetime(2026, 9, 28, 3, 5, tzinfo=UTC))

    await repo.set_status(test=test, status=AbTestStatus.RUNNING)
    await repo.set_status(
        test=test, status=AbTestStatus.PAUSED, stopped_at=datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
    )

    assert test.paused_by_ads is False
    assert test.id not in {t.id for t in await repo.list_ads_paused()}


@pytest.mark.integration
async def test_a_variant_is_only_reachable_from_its_own_workspace(
    db_session: AsyncSession, organization: Organization
) -> None:
    """The image route's guard is a JOIN, so only a real database proves it.

    That route is called once per photo, and resolving the test separately cost
    three round trips per image. Folding the tenancy check into the query is
    what removed them — and it is only safe while the predicate is actually
    there, which no fake repository can show.
    """
    mine = await _workspace(db_session, organization.id)
    theirs = await _workspace(db_session, organization.id, name="Foreign")
    repo = AbTestRepository(db_session)
    test = await repo.create(
        workspace_id=mine.id,
        nm_id=NM_FLOWER_DRESS,
        vendor_code="KID_DRESS_FLORAL",
        name="Test",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    variants = VariantRepository(db_session)
    variant = await variants.add(
        test_id=test.id,
        image_path=f"{test.id}/0.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="0.jpg",
    )

    found = await variants.get_scoped(workspace_id=mine.id, test_id=test.id, variant_id=variant.id)
    stranger = await variants.get_scoped(
        workspace_id=theirs.id, test_id=test.id, variant_id=variant.id
    )

    assert found is not None
    assert found.id == variant.id
    assert stranger is None
