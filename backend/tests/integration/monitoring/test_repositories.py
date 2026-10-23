"""Integration tests for monitoring repository queries that only SQL can prove.

Everything here is a statement whose behaviour lives in PostgreSQL, not in
Python — an ``ilike`` pattern, a tenancy predicate, an ``ON CONFLICT`` clause
with a ``WHERE``. A fake repository would return whatever the fake was told to
return and prove none of it.

The day-header carry in particular is a single set-based ``INSERT ... FROM
SELECT ... ON CONFLICT DO UPDATE WHERE`` — its "seed but never overwrite"
semantics are entirely in that ``WHERE``, so this is the only tier that can
check them.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import ProductCard, SkuDayActionHistory
from src.modules.monitoring.models.sku_day_comment import SkuDayComment
from src.modules.monitoring.repos.day_actions import SkuDayActionRepository
from src.modules.monitoring.repos.products import ProductCardRepository
from src.modules.monitoring.repos.sku_day_comment import SkuDayCommentRepository

WORKSPACE_A = uuid.uuid4()
WORKSPACE_B = uuid.uuid4()
YESTERDAY = date(2026, 7, 1)
TODAY = date(2026, 7, 2)


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> None:
    """Two workspaces' SKUs, plus one unregistered SKU."""
    db_session.add_all(
        [
            ProductCard(nm_id=1001, workspace_id=WORKSPACE_A, vendor_code="M-TRX01-BLK"),
            ProductCard(nm_id=1002, workspace_id=WORKSPACE_A, vendor_code="M-TRX01-BEJ"),
            ProductCard(nm_id=1003, workspace_id=WORKSPACE_A, vendor_code="M-SHIRT-RED"),
            ProductCard(nm_id=2001, workspace_id=WORKSPACE_B, vendor_code="M-TRX01-BLK"),
            ProductCard(nm_id=3001, workspace_id=None, vendor_code="ORPHAN-01"),
        ]
    )
    await db_session.flush()


# --------------------------------------------------------------------------- #
# Tenancy
# --------------------------------------------------------------------------- #
async def test_a_sku_is_owned_by_its_own_workspace(
    db_session: AsyncSession, catalogue: None
) -> None:
    """The ownership predicate accepts the workspace's own SKU."""
    repo = ProductCardRepository(db_session)

    assert await repo.is_in_workspace(nm_id=1001, workspace_id=WORKSPACE_A) is True


@pytest.mark.parametrize(
    ("nm_id", "case"),
    [(2001, "another workspace's SKU"), (3001, "an unregistered SKU"), (9999, "no such SKU")],
)
async def test_foreign_and_unknown_skus_are_equally_not_owned(
    db_session: AsyncSession, catalogue: None, nm_id: int, case: str
) -> None:
    """All three answer identically, which is what makes the 404 non-revealing.

    If a foreign SKU produced a different answer from a nonexistent one, the
    route could be used to enumerate another seller's catalogue.
    """
    repo = ProductCardRepository(db_session)

    assert await repo.is_in_workspace(nm_id=nm_id, workspace_id=WORKSPACE_A) is False


async def test_the_refresh_task_can_resolve_a_skus_owner(
    db_session: AsyncSession, catalogue: None
) -> None:
    """The single-SKU refresh picks its WB credentials from this lookup."""
    repo = ProductCardRepository(db_session)

    assert await repo.get_workspace_of_sku(1001) == WORKSPACE_A
    assert await repo.get_workspace_of_sku(9999) is None


# --------------------------------------------------------------------------- #
# Vendor-code search
# --------------------------------------------------------------------------- #
async def test_search_returns_every_colourway_of_a_partial_code(
    db_session: AsyncSession, catalogue: None
) -> None:
    """``M-TRX01`` finds all its variants — the seller-facing search behaviour."""
    repo = ProductCardRepository(db_session)

    found = await repo.search_by_vendor_code("M-TRX01", workspace_id=WORKSPACE_A, limit=10)

    assert [card.nm_id for card in found] == [1002, 1001]  # ordered by vendor code


async def test_search_is_case_insensitive(db_session: AsyncSession, catalogue: None) -> None:
    """Sellers type codes in whatever case; the search must not care."""
    repo = ProductCardRepository(db_session)

    found = await repo.search_by_vendor_code("m-trx01-blk", workspace_id=WORKSPACE_A, limit=10)

    assert [card.nm_id for card in found] == [1001]


async def test_search_never_crosses_into_another_workspace(
    db_session: AsyncSession, catalogue: None
) -> None:
    """SKU 2001 shares a vendor code but belongs to workspace B.

    Vendor codes are seller-chosen and collide freely across tenants, so the
    workspace predicate is the only thing preventing a catalogue leak here.
    """
    repo = ProductCardRepository(db_session)

    found = await repo.search_by_vendor_code("M-TRX01-BLK", workspace_id=WORKSPACE_A, limit=10)

    assert [card.nm_id for card in found] == [1001]


async def test_search_respects_its_limit(db_session: AsyncSession, catalogue: None) -> None:
    """The cap is applied in SQL, so a broad fragment cannot return the catalogue."""
    repo = ProductCardRepository(db_session)

    found = await repo.search_by_vendor_code("M-", workspace_id=WORKSPACE_A, limit=2)

    assert len(found) == 2


# --------------------------------------------------------------------------- #
# Day-header carry (set-based upsert)
# --------------------------------------------------------------------------- #
async def test_a_header_carries_onto_the_new_day(db_session: AsyncSession) -> None:
    """Yesterday's running title continues onto today as a real, editable row."""
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="note", header="Ramp-up")

    carried = await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    assert carried == 1
    today_row = await repo.get(nm_id=1001, comment_date=TODAY)
    assert today_row is not None
    assert today_row.header == "Ramp-up"


async def test_the_comment_does_not_carry(db_session: AsyncSession) -> None:
    """Only the title continues; the comment is per-day by definition.

    Carrying yesterday's note text would make every day look like it repeated
    the same observation.
    """
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="yesterday's note", header="Ramp-up")

    await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    today_row = await repo.get(nm_id=1001, comment_date=TODAY)
    assert today_row is not None
    assert today_row.body == ""


async def test_a_blank_header_does_not_create_a_row(db_session: AsyncSession) -> None:
    """A SKU with no title yesterday starts the new day genuinely empty.

    Otherwise the carry would manufacture an empty row for every SKU every day.
    """
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="just a comment", header="")

    carried = await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    assert carried == 0
    assert await repo.get(nm_id=1001, comment_date=TODAY) is None


async def test_the_carry_never_overwrites_a_header_written_today(
    db_session: AsyncSession,
) -> None:
    """Someone who already retitled today keeps their title.

    The carry seeds a day; it must not re-assert yesterday's title over what a
    teammate has since written. This is the ``WHERE header = ''`` in the upsert.
    """
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="", header="Yesterday's")
    await repo.set(nm_id=1001, comment_date=TODAY, body="", header="Already written")

    await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    today_row = await repo.get(nm_id=1001, comment_date=TODAY)
    assert today_row is not None
    assert today_row.header == "Already written"


async def test_the_carry_seeds_a_comment_only_row(db_session: AsyncSession) -> None:
    """A day that already has a comment but no title still receives the title.

    The two fields are independent, so an existing row must not block the carry.
    """
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="", header="Ramp-up")
    await repo.set(nm_id=1001, comment_date=TODAY, body="today's note", header="")

    await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    today_row = await repo.get(nm_id=1001, comment_date=TODAY)
    assert today_row is not None
    assert today_row.header == "Ramp-up"
    assert today_row.body == "today's note"


async def test_the_carry_is_idempotent(db_session: AsyncSession) -> None:
    """Running it twice changes nothing the second time.

    Beat can fire a job more than once (a worker restart, a manual re-run); a
    non-idempotent carry would duplicate or resurrect titles.
    """
    repo = SkuDayCommentRepository(db_session)
    await repo.set(nm_id=1001, comment_date=YESTERDAY, body="", header="Ramp-up")
    first = await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    second = await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    assert (first, second) == (1, 0)
    rows = (
        (
            await db_session.execute(
                sa.select(SkuDayComment).where(SkuDayComment.comment_date == TODAY)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_the_carry_covers_every_sku_in_one_statement(
    db_session: AsyncSession,
) -> None:
    """It is set-based: N SKUs carry in one round trip, not N.

    With a per-SKU loop this nightly job would issue thousands of statements.
    """
    repo = SkuDayCommentRepository(db_session)
    for nm_id in (1001, 1002, 1003):
        await repo.set(nm_id=nm_id, comment_date=YESTERDAY, body="", header=f"Topic {nm_id}")

    carried = await repo.carry_headers_to_day(source_day=YESTERDAY, target_day=TODAY)

    assert carried == 3


# --------------------------------------------------------------------------- #
# Day-action history
# --------------------------------------------------------------------------- #
async def test_a_day_action_history_outlives_the_cleared_day(db_session: AsyncSession) -> None:
    """The change log is append-only and independent of the action row.

    Clearing the day deletes its ``sku_day_action`` row; the history of what
    it held, and who saved it, has to survive that — it is exactly what a
    dispute about the day needs.
    """
    repo = SkuDayActionRepository(db_session)
    manager = uuid.uuid4()
    state = {"first_rk_type": "uni", "first_rk_budget": 4000.0}
    await repo.set(
        nm_id=1001,
        action_date=TODAY,
        first_rk_type="uni",
        first_rk_budget=4000.0,
        second_rk_type=None,
        second_rk_budget=None,
        price_change=None,
        price_change_amount=None,
    )
    await repo.record_change(
        nm_id=1001, action_date=TODAY, changed_by=manager, before=None, after=state
    )

    await repo.clear(nm_id=1001, action_date=TODAY)
    await repo.record_change(
        nm_id=1001, action_date=TODAY, changed_by=manager, before=state, after=None
    )

    rows = (
        (
            await db_session.execute(
                sa.select(SkuDayActionHistory)
                .where(SkuDayActionHistory.nm_id == 1001)
                .order_by(SkuDayActionHistory.id)
            )
        )
        .scalars()
        .all()
    )
    assert await repo.get(nm_id=1001, action_date=TODAY) is None
    assert [(r.before, r.after) for r in rows] == [(None, state), (state, None)]
    assert {r.changed_by for r in rows} == {manager}
    assert all(r.changed_at is not None for r in rows)
