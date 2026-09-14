"""Seeing your own sessions, and ending one of them.

The rule this file exists for is the one that is easy to get wrong and silent
when you do: **a session is a family, and ending one must end exactly one.**
Reaching for the account-wide lever from a family-scoped act is what turned one
woken-up laptop into a team-wide sign-out on 2026-07-27 (see
``services/revocation.py``), so "the other lineages survive" is asserted here
rather than assumed.

The second rule is who may: a lineage belonging to somebody else is **not
found**, never "forbidden" — a family id could only have come from another
account's list, and saying it exists would make the route an oracle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.exceptions import NotFoundError
from src.core.ids import uuid7
from src.modules.users.services.sessions import end_session, list_sessions
from tests.support.fakes import FakeRefreshTokenRepository


async def _node(
    tokens: FakeRefreshTokenRepository,
    *,
    user_id,
    family_id,
    created_at: datetime | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
    revoked: bool = False,
    expires_in_days: int = 7,
):
    """Add one refresh row to a lineage."""
    token = await tokens.create(
        token_id=uuid7(),
        user_id=user_id,
        family_id=family_id,
        token_hash=f"hash-{uuid7()}",
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    if created_at is not None:
        token.created_at = created_at
    token.is_revoked = revoked
    return token


@pytest.mark.asyncio
async def test_one_login_is_one_row_however_often_it_rotated() -> None:
    """A lineage rotated all day is one session, not ninety-six of them."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    user_id, family = uuid7(), uuid7()
    start = datetime.now(UTC) - timedelta(hours=3)
    for minute in range(0, 180, 15):
        await _node(
            tokens,
            user_id=user_id,
            family_id=family,
            created_at=start + timedelta(minutes=minute),
            user_agent="Mozilla/5.0 (Macintosh)",
            ip_address="203.0.113.7",
        )

    # Act
    rows = await list_sessions(tokens=tokens, user_id=user_id)

    # Assert
    assert len(rows) == 1
    assert rows[0].started_at == start
    assert rows[0].last_seen_at == start + timedelta(minutes=165)


@pytest.mark.asyncio
async def test_the_row_reports_where_the_session_is_now() -> None:
    """A laptop that moved networks is still one session, at its new address."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    user_id, family = uuid7(), uuid7()
    earlier = datetime.now(UTC) - timedelta(hours=1)
    await _node(
        tokens,
        user_id=user_id,
        family_id=family,
        created_at=earlier,
        user_agent="Mozilla/5.0 (Macintosh)",
        ip_address="203.0.113.7",
    )
    await _node(
        tokens,
        user_id=user_id,
        family_id=family,
        created_at=datetime.now(UTC),
        user_agent="Mozilla/5.0 (Macintosh)",
        ip_address="198.51.100.4",
    )

    # Act
    rows = await list_sessions(tokens=tokens, user_id=user_id)

    # Assert
    assert [row.ip_address for row in rows] == ["198.51.100.4"]
    assert rows[0].started_at == earlier


@pytest.mark.asyncio
async def test_an_ended_session_leaves_the_list() -> None:
    """This list is for deciding what to end; a dead session is not a decision."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    user_id, live, dead = uuid7(), uuid7(), uuid7()
    await _node(tokens, user_id=user_id, family_id=live)
    await _node(tokens, user_id=user_id, family_id=dead, revoked=True)

    # Act
    rows = await list_sessions(tokens=tokens, user_id=user_id)

    # Assert
    assert [row.family_id for row in rows] == [live]


@pytest.mark.asyncio
async def test_an_expired_session_leaves_the_list() -> None:
    """Same for one that simply ran out — nothing to end there either."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    user_id, live = uuid7(), uuid7()
    await _node(tokens, user_id=user_id, family_id=live)
    await _node(tokens, user_id=user_id, family_id=uuid7(), expires_in_days=-1)

    # Act
    rows = await list_sessions(tokens=tokens, user_id=user_id)

    # Assert
    assert [row.family_id for row in rows] == [live]


@pytest.mark.asyncio
async def test_the_list_is_somebody_elses_business_only_for_them() -> None:
    """Scoped by user_id in the query, so no argument returns another's row."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    mine, theirs = uuid7(), uuid7()
    await _node(tokens, user_id=mine, family_id=uuid7())
    await _node(tokens, user_id=theirs, family_id=uuid7())

    # Act
    rows = await list_sessions(tokens=tokens, user_id=mine)

    # Assert
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ending_one_session_leaves_the_others_alone() -> None:
    """The 2026-07-27 mistake, pinned: family scope, not account scope."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    user_id, phone, laptop = uuid7(), uuid7(), uuid7()
    await _node(tokens, user_id=user_id, family_id=phone)
    await _node(tokens, user_id=user_id, family_id=laptop)

    # Act
    await end_session(tokens=tokens, user_id=user_id, family_id=phone)

    # Assert
    live = {t.family_id for t in tokens.tokens.values() if not t.is_revoked}
    assert live == {laptop}


@pytest.mark.asyncio
async def test_ending_a_stranger_s_session_is_not_found() -> None:
    """404, not 403 — a family id must not become an existence oracle."""
    # Arrange
    tokens = FakeRefreshTokenRepository()
    mine, theirs = uuid7(), uuid7()
    stranger_family = uuid7()
    await _node(tokens, user_id=theirs, family_id=stranger_family)

    # Act / Assert
    with pytest.raises(NotFoundError):
        await end_session(tokens=tokens, user_id=mine, family_id=stranger_family)
    assert all(not t.is_revoked for t in tokens.tokens.values())
