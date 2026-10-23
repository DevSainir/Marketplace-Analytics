"""Concurrency probes for writes that two people can perform at the same time.

Everything here is a lost-update or double-insert hazard that a single-threaded
test can never surface: the row is written twice, or read-then-written by two
callers whose statements interleave. The database's own constraints and
``ON CONFLICT`` clauses are what make these safe, so they are exercised with
genuinely concurrent sessions rather than sequential calls.

The team shares one workspace and edits the same SKUs, so "two managers clicked
at once" is the normal case, not an exotic one.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.performance

NM_ID = 770001
DAY = date(2026, 7, 1)


@pytest.fixture
async def sessions(database_url: str):
    """A session factory over an ordinary pooled engine, plus cleanup.

    Yields:
        A ``(factory, engine)`` pair; rows written by the test are removed after.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, pool_size=10, max_overflow=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM monitoring.sku_day_comment WHERE nm_id = :nm"),
                {"nm": NM_ID},
            )
            await conn.execute(
                sa.text("DELETE FROM monitoring.product_card WHERE nm_id = :nm"), {"nm": NM_ID}
            )
            await conn.execute(
                sa.text("DELETE FROM auth.refresh_tokens WHERE token_hash LIKE 'race-%'")
            )
            await conn.execute(sa.text("DELETE FROM auth.users WHERE email LIKE 'race-%'"))
        await engine.dispose()


async def test_simultaneous_note_saves_leave_exactly_one_row(sessions) -> None:
    """Ten managers saving the same day's note produce one row, not ten.

    The note is keyed ``(nm_id, comment_date)`` and written with an upsert; a
    read-then-insert would race here and either duplicate the row or blow up on
    the unique constraint mid-request.
    """
    from src.modules.monitoring.repos.sku_day_comment import SkuDayCommentRepository

    async def save(index: int) -> None:
        async with sessions() as session:
            await SkuDayCommentRepository(session).set(
                nm_id=NM_ID, comment_date=DAY, body=f"note {index}", header="Topic"
            )
            await session.commit()

    await asyncio.gather(*(save(i) for i in range(10)), return_exceptions=False)

    async with sessions() as session:
        count = await session.scalar(
            sa.text(
                "SELECT count(*) FROM monitoring.sku_day_comment "
                "WHERE nm_id = :nm AND comment_date = :day"
            ),
            {"nm": NM_ID, "day": DAY},
        )
    assert count == 1


async def test_last_write_wins_without_losing_the_row(sessions) -> None:
    """Concurrent edits settle on one of the submitted values, never on nothing.

    "Last write wins" is the product decision for shared notes; silently
    clearing the note because two writes collided would not be.
    """
    from src.modules.monitoring.repos.sku_day_comment import SkuDayCommentRepository

    bodies = [f"note {i}" for i in range(5)]

    async def save(body: str) -> None:
        async with sessions() as session:
            await SkuDayCommentRepository(session).set(
                nm_id=NM_ID, comment_date=DAY, body=body, header="Topic"
            )
            await session.commit()

    await asyncio.gather(*(save(body) for body in bodies))

    async with sessions() as session:
        stored = await session.scalar(
            sa.text(
                "SELECT body FROM monitoring.sku_day_comment "
                "WHERE nm_id = :nm AND comment_date = :day"
            ),
            {"nm": NM_ID, "day": DAY},
        )
    assert stored in bodies


async def test_a_duplicate_registration_race_yields_one_account(sessions) -> None:
    """Two signups for the same email at once: one wins, one gets a clean error.

    The service pre-checks for an existing email, which both requests pass; the
    unique index is the only thing that stops a duplicate account, and the
    service must translate that into a conflict rather than a 500.
    """
    from sqlalchemy.exc import IntegrityError
    from src.modules.users.models import User

    email = f"race-{uuid.uuid4().hex[:8]}@example.com"

    async def register() -> str:
        async with sessions() as session:
            session.add(User(email=email, hashed_password="x", is_active=True, role="user"))
            try:
                await session.commit()
                return "created"
            except IntegrityError:
                await session.rollback()
                return "conflict"

    outcomes = await asyncio.gather(*(register() for _ in range(5)))

    assert outcomes.count("created") == 1
    assert outcomes.count("conflict") == 4


async def test_a_refresh_token_is_consumable_exactly_once(sessions) -> None:
    """Twenty parallel rotations of one secret: one succeeds, nineteen do not.

    This is breach detection's foundation under real contention. If more than
    one caller could consume the token, a stolen refresh cookie would rotate
    successfully alongside the legitimate one and never be noticed.
    """
    from src.core.ids import uuid7
    from src.modules.users.models import RefreshToken, User
    from src.modules.users.repos import RefreshTokenRepository

    user_id = uuid7()
    token_id = uuid7()
    async with sessions() as session:
        session.add(
            User(
                id=user_id,
                email=f"race-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                is_active=True,
                role="user",
            )
        )
        session.add(
            RefreshToken(
                id=token_id,
                user_id=user_id,
                family_id=uuid7(),
                token_hash=f"race-{token_id}",
                expires_at=sa.func.now() + sa.text("interval '7 days'"),
            )
        )
        await session.commit()

    async def consume() -> bool:
        async with sessions() as session:
            won = await RefreshTokenRepository(session).consume(token_id)
            await session.commit()
            return won

    outcomes = await asyncio.gather(*(consume() for _ in range(20)))

    assert outcomes.count(True) == 1


async def test_concurrent_catalogue_upserts_do_not_duplicate_a_sku(sessions) -> None:
    """Parallel harvest passes for one SKU converge on a single card row.

    The nightly harvest and a manual per-SKU refresh can overlap; a
    non-idempotent upsert would leave two cards and make the ownership guard's
    answer depend on row order.
    """
    from src.modules.monitoring.repos.products import ProductCardRepository

    workspace_id = uuid.uuid4()

    async def upsert(index: int) -> None:
        async with sessions() as session:
            await ProductCardRepository(session).upsert_many(
                [
                    {
                        "nm_id": NM_ID,
                        "workspace_id": workspace_id,
                        "vendor_code": f"M-RACE-{index}",
                        "title": "race",
                    }
                ]
            )
            await session.commit()

    await asyncio.gather(*(upsert(i) for i in range(8)))

    async with sessions() as session:
        count = await session.scalar(
            sa.text("SELECT count(*) FROM monitoring.product_card WHERE nm_id = :nm"),
            {"nm": NM_ID},
        )
    assert count == 1
