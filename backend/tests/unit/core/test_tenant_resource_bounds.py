"""The three per-tenant resource bounds added for register P1.13.

`max_workspaces` and `max_managers` already existed and are what a customer
bought. These are a different thing: safety bounds on shared storage, of the
same family as the upload caps in P0.4. An authenticated tenant that reaches one
has stopped using the feature and started filling the database.

Grouped in one file rather than scattered across three modules' test
directories, because what they have in common — the bound, the refusal, and the
legitimate use each one must *not* break — is the thing worth reading together.
That last part is what the tests mostly pin: a bound that refuses a customer
re-uploading their own catalogue would be removed within the week, and rightly.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.ab_tests.schemas import AbTestCreate
from src.modules.ab_tests.services.catalog import AbTestCatalogService
from src.modules.finreports.schemas.cost_price import CostPriceInput
from src.modules.finreports.services.cost_price import CostPriceService
from src.modules.monitoring.contract import WorkspaceCard
from src.modules.monitoring.services.analytics.annotations import DayAnnotationAnalytics

#: A resolved catalogue card. Creating a test now requires one, because the
#: article is checked against the workspace catalogue before anything is
#: written — `nm_id=1` used to be accepted straight off the body.
_CARD = WorkspaceCard(nm_id=995716075, vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК", title="Брюки")


class FakeCostRepo:
    """Counts and upserts in memory, with the surface the quota check uses."""

    def __init__(self, stored: set[int] | None = None) -> None:
        """Start holding costs for the given SKUs."""
        self.stored = stored or set()
        self.upserted: list[dict[str, Any]] = []

    async def count_for_workspace(self, workspace_id: uuid.UUID) -> int:
        """How many SKUs are costed."""
        return len(self.stored)

    async def count_existing(self, *, workspace_id: uuid.UUID, nm_ids: Any) -> int:
        """How many of these SKUs are already costed."""
        return len(self.stored & set(nm_ids))

    async def upsert_many(self, rows: Any) -> int:
        """Record the write and report how many rows it covered."""
        self.upserted = list(rows)
        return len(self.upserted)


def _cost_service(repo: FakeCostRepo) -> CostPriceService:
    """Build the service with only the collaborator these cases exercise."""
    return CostPriceService(cost_repo=repo, pnl_repo=None)


def _items(nm_ids: list[int]) -> list[CostPriceInput]:
    """Build a save batch for the given SKUs."""
    return [CostPriceInput(nm_id=nm_id, cost=Decimal("100"), currency="RUB") for nm_id in nm_ids]


# --------------------------------------------------------------------------- #
# Cost prices — bounded by row count per workspace
# --------------------------------------------------------------------------- #
async def test_a_batch_inside_the_bound_is_saved(settings_override: Any) -> None:
    """The ordinary case, so the refusals below are not passing vacuously."""
    repo = FakeCostRepo()

    with settings_override(max_cost_price_rows_per_workspace=10):
        result = await _cost_service(repo).save_cost_prices(
            workspace_id=uuid.uuid4(), items=_items([1, 2, 3])
        )

    assert result.saved == 3


async def test_a_batch_that_would_cross_the_bound_is_refused(settings_override: Any) -> None:
    """Otherwise a script fills shared storage one upload at a time."""
    repo = FakeCostRepo(stored={1, 2, 3})

    with (
        settings_override(max_cost_price_rows_per_workspace=4),
        pytest.raises(ValidationError) as excinfo,
    ):
        await _cost_service(repo).save_cost_prices(
            workspace_id=uuid.uuid4(), items=_items([10, 11, 12])
        )

    assert "лимит себестоимостей" in excinfo.value.message
    assert repo.upserted == [], "nothing may be written once the batch is refused"


async def test_re_uploading_the_same_catalogue_at_the_bound_still_works(
    settings_override: Any,
) -> None:
    """The bound counts what a batch ADDS, not what it touches.

    A workspace sitting exactly at its cap re-uploading its own spreadsheet is
    the single most likely legitimate use of this endpoint. Counting overwrites
    as new rows would refuse it, and a bound that does that gets removed within
    the week — correctly.
    """
    repo = FakeCostRepo(stored={1, 2, 3})

    with settings_override(max_cost_price_rows_per_workspace=3):
        result = await _cost_service(repo).save_cost_prices(
            workspace_id=uuid.uuid4(), items=_items([1, 2, 3])
        )

    assert result.saved == 3


async def test_one_new_sku_past_a_full_workspace_is_refused(settings_override: Any) -> None:
    """The boundary itself: full means full, even for a batch of mostly overwrites."""
    repo = FakeCostRepo(stored={1, 2, 3})

    with settings_override(max_cost_price_rows_per_workspace=3), pytest.raises(ValidationError):
        await _cost_service(repo).save_cost_prices(
            workspace_id=uuid.uuid4(), items=_items([1, 2, 3, 4])
        )


async def test_a_batch_repeating_one_sku_counts_it_once(settings_override: Any) -> None:
    """Duplicates in one upload are one row, so they must cost one slot."""
    repo = FakeCostRepo()

    with settings_override(max_cost_price_rows_per_workspace=1):
        result = await _cost_service(repo).save_cost_prices(
            workspace_id=uuid.uuid4(), items=_items([7, 7, 7])
        )

    assert result.saved == 3


# --------------------------------------------------------------------------- #
# SKU-day comments — bounded by date, because there is no tenant to count
# --------------------------------------------------------------------------- #
class FakeCommentRepo:
    """Enough of the comment repository for the date guard to be reached."""

    def __init__(self) -> None:
        """Start with nothing stored."""
        self.written: list[tuple[int, Any]] = []

    async def get(self, *, nm_id: int, comment_date: Any) -> None:
        """No note on file."""
        return

    async def set(self, *, nm_id: int, comment_date: Any, body: str, header: str) -> None:
        """Record that a note was written."""
        self.written.append((nm_id, comment_date))

    async def clear(self, *, nm_id: int, comment_date: Any) -> None:
        """Record a clear as a no-op."""


def _annotations(repo: FakeCommentRepo) -> DayAnnotationAnalytics:
    """Build the service with only the collaborator these cases exercise."""
    return DayAnnotationAnalytics(day_comment_repo=repo, day_action_repo=None)


async def test_a_note_on_a_nearby_day_is_saved(settings_override: Any) -> None:
    """Yesterday and tomorrow are the normal case and must stay free."""
    repo = FakeCommentRepo()

    with settings_override(sku_comment_max_days_from_today=30):
        await _annotations(repo).set_day_note(
            nm_id=1, comment_date=moscow_today() - timedelta(days=1), body="был всплеск"
        )

    assert len(repo.written) == 1


@pytest.mark.parametrize(
    ("offset", "case"),
    [(400, "far future"), (-400, "far past")],
)
async def test_a_note_far_outside_the_window_is_refused(
    offset: int, case: str, settings_override: Any
) -> None:
    """Bounded in both directions: a script can walk dates either way."""
    repo = FakeCommentRepo()

    with (
        settings_override(sku_comment_max_days_from_today=30),
        pytest.raises(ValidationError) as excinfo,
    ):
        await _annotations(repo).set_day_note(
            nm_id=1, comment_date=moscow_today() + timedelta(days=offset), body="x"
        )

    assert "диапазон" in excinfo.value.message
    assert repo.written == []


async def test_the_window_edge_is_inclusive(settings_override: Any) -> None:
    """A bound nobody can state precisely is one nobody can rely on."""
    repo = FakeCommentRepo()

    with settings_override(sku_comment_max_days_from_today=30):
        await _annotations(repo).set_day_note(
            nm_id=1, comment_date=moscow_today() + timedelta(days=30), body="x"
        )

    assert len(repo.written) == 1


# --------------------------------------------------------------------------- #
# A/B tests — bounded by count per workspace
# --------------------------------------------------------------------------- #
class FakeTestRepo:
    """Counts tests in memory; `create` is never reached once the bound bites."""

    def __init__(self, *, held: int = 0) -> None:
        """Start holding this many tests."""
        self.held = held
        self.created = 0

    async def count_for_workspace(self, workspace_id: uuid.UUID) -> int:
        """How many tests the workspace holds, in any status."""
        return self.held

    async def create(self, **kwargs: Any) -> Any:
        """Record that a test would have been created."""
        self.created += 1
        raise AssertionError("create must not be reached in these cases")


def _catalog(repo: FakeTestRepo) -> AbTestCatalogService:
    """Build the service with only the collaborator these cases exercise."""
    return AbTestCatalogService(
        tests=repo,
        variants=None,
        exposures=None,
        stats=None,
        snapshots=None,
        campaigns=None,
        media_store=None,
    )


async def test_a_workspace_at_its_test_bound_cannot_create_another(
    settings_override: Any,
) -> None:
    """Finished tests count: they keep their rows, variants and uploaded images."""
    repo = FakeTestRepo(held=5)

    with (
        settings_override(max_ab_tests_per_workspace=5),
        pytest.raises(ValidationError) as excinfo,
    ):
        await _catalog(repo).create_test(
            workspace_id=uuid.uuid4(),
            payload=AbTestCreate(nm_id=_CARD.nm_id, name="проверка"),
            # A resolved card: the bound is about how many tests exist, not which
            # article they name. `nm_id=1` used to be accepted here and in
            # production, which is why the article is now resolved first.
            card=_CARD,
        )

    assert "лимит А/Б-тестов" in excinfo.value.message
    assert repo.created == 0
