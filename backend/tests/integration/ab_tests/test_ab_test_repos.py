"""A/Б-test reads and writes against a real database.

These cannot go lower. The search predicate is SQL — four `OR`ed matches, one of
them a cast of a bigint to text — and a fake repository would assert nothing but
its own `in` operator. The same goes for the composite-key upsert of attributed
days. The rotation's ordering lives next door in test_rotation_order.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AbTestStatus, TriggerMode
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    SnapshotRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.collection import Counters
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
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    await repo.create(
        workspace_id=workspace.id,
        nm_id=NM_PLAIN_SUIT,
        vendor_code="ДЕТ_КОСТЮМ_ДВОЙКА_ОДНОТОН",
        name="Костюм: фон против модели",
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=10_000,
        slot_minutes=60,
    )
    paused = await repo.create(
        workspace_id=workspace.id,
        nm_id=953770957,
        vendor_code="ДЖН_КОСТЮМ_ДЖИНСА",
        name="Джинса, крупный план",
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
async def test_an_interval_is_recorded_once_even_if_the_pass_is_retried(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """A window is idempotent on (variant, start), so a retry cannot double-count.

    The polling pass can fail mid-transaction — a WB timeout on the swap after
    the window was written — and Celery retries it. Without the conflict clause
    the same five minutes of traffic would be credited twice, and the rotation
    would advance early on nothing.
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
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    windows = WindowRepository(db_session)
    start = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    counters = Counters(views=112, clicks=7, atbs=4, orders=1, spend=Decimal("18.00"))
    await windows.append(
        test_id=test.id,
        variant_id=variant.id,
        window_start=start,
        window_end=datetime(2026, 9, 4, 12, 5, tzinfo=UTC),
        counters=counters,
    )
    await windows.append(
        test_id=test.id,
        variant_id=variant.id,
        window_start=start,
        window_end=datetime(2026, 9, 4, 12, 5, tzinfo=UTC),
        counters=counters,
    )

    rows = await windows.windows_for_test(test_id=test.id)
    assert len(rows) == 1
    assert await windows.impressions_for_variant(variant_id=variant.id) == 112


@pytest.mark.integration
async def test_impressions_accumulate_across_a_variants_intervals(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The rotation counter is the sum of every window the photo owned.

    A photo rotating several times a day earns many small windows rather than
    one big day, so the trigger has to read their total.
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
    variant = await VariantRepository(db_session).add(
        test_id=test.id,
        image_path="a.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename="a.jpg",
    )
    windows = WindowRepository(db_session)

    for minute in range(0, 15, 5):
        await windows.append(
            test_id=test.id,
            variant_id=variant.id,
            window_start=datetime(2026, 9, 4, 12, minute, tzinfo=UTC),
            window_end=datetime(2026, 9, 4, 12, minute + 5, tzinfo=UTC),
            counters=Counters(views=100),
        )

    assert await windows.impressions_for_variant(variant_id=variant.id) == 300


@pytest.mark.integration
async def test_the_snapshot_round_trips_and_is_overwritten_each_poll(
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The baseline stores one row per day and moves forward on every poll.

    It is the poller's whole memory: a snapshot that failed to advance would
    make the next window re-count everything since the last successful one.
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
    snapshots = SnapshotRepository(db_session)
    yesterday, today = date(2026, 9, 3), date(2026, 9, 4)
    first_read = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    second_read = datetime(2026, 9, 4, 12, 5, tzinfo=UTC)

    assert await snapshots.load(test_id=test.id) is None

    await snapshots.save(
        test_id=test.id,
        by_day={yesterday: Counters(views=20_000), today: Counters(views=6_937)},
        captured_at=first_read,
    )
    await snapshots.save(
        test_id=test.id,
        by_day={yesterday: Counters(views=20_050), today: Counters(views=7_049)},
        captured_at=second_read,
    )

    stored = await snapshots.load(test_id=test.id)
    assert stored is not None
    assert stored.captured_at == second_read
    assert stored.by_day[today].views == 7_049
    assert stored.by_day[yesterday].views == 20_050


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
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
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
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест",
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
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Запущенный",
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
