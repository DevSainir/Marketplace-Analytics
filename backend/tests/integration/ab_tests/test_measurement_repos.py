"""What a rotation measured, against a real database.

Its own file rather than more of test_ab_test_repos.py: `repos/measurements.py`
is a separate owner — the two tables here move on every polling pass, while a
test's own rows move only when a photo does — and the combined file had grown
past the repository's 500-line ceiling.

These cannot go lower either. The interval upsert is a composite-key
`ON CONFLICT`, and a fake would assert nothing but its own dictionary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.repos import (
    AbTestRepository,
    SnapshotRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.collection import Counters
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

NM_FLOWER_DRESS = 995716075


async def _workspace(
    session: AsyncSession, organization_id: uuid.UUID, name: str = "Демо"
) -> Workspace:
    """Persist a workspace, inside the tenant that owns it."""
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization_id, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


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
