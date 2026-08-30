"""The audit log's central claim, checked against a real PostgreSQL (P1.3).

Everything else about this table is ordinary. The one property that makes it
worth having is that a row, once written, cannot be changed or removed — and
that property lives in the database, not in the repository, precisely because
the threat model includes an attacker running our own code. A test that only
exercised :class:`AuditLogRepository` would prove the repository has no
``update`` method, which nobody doubted.

So these go around the ORM and issue the SQL directly.

Also pinned here: the absence of foreign keys on ``actor_user_id`` and
``organization_id``. Adding one later would look like tidying and would quietly
re-arm the failure this table exists to survive — deleting the account blanking
every record of what that account did.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import AuditEvent
from src.modules.organizations.repos import AuditLogRepository

pytestmark = pytest.mark.integration


async def _one_entry(session: AsyncSession) -> uuid.UUID:
    """Append a single entry and return its id."""
    repo = AuditLogRepository(session)
    entry = await repo.append(
        event=str(AuditEvent.MEMBER_REMOVED),
        actor_user_id=uuid.uuid4(),
        actor_email="manager@example.com",
        organization_id=uuid.uuid4(),
        target_type="membership",
        target_id=str(uuid.uuid4()),
        ip_address="203.0.113.7",
        user_agent="Mozilla/5.0",
        metadata={"role_before": "manager", "role_after": None},
    )
    return entry.id


async def test_an_entry_can_be_written_and_read_back(db_session: AsyncSession) -> None:
    """The ordinary case, so the refusals below are not passing vacuously."""
    # Arrange / Act
    entry_id = await _one_entry(db_session)

    # Assert
    stored = (
        await db_session.execute(
            sa.text(
                "SELECT event, actor_email, metadata FROM organizations.audit_log WHERE id = :id"
            ),
            {"id": entry_id},
        )
    ).one()
    assert stored.event == "MEMBER_REMOVED"
    assert stored.actor_email == "manager@example.com"
    assert stored.metadata == {"role_before": "manager", "role_after": None}


async def test_an_entry_cannot_be_updated(db_session: AsyncSession) -> None:
    """Rewriting history is the move this table exists to make impossible."""
    # Arrange
    entry_id = await _one_entry(db_session)

    # Act / Assert
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            sa.text(
                "UPDATE organizations.audit_log "
                "SET actor_email = 'someone.else@example.com' WHERE id = :id"
            ),
            {"id": entry_id},
        )

    assert "append-only" in str(excinfo.value)


async def test_an_entry_cannot_be_deleted(db_session: AsyncSession) -> None:
    """Deleting the evidence is the other half of the same move."""
    # Arrange
    entry_id = await _one_entry(db_session)

    # Act / Assert
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            sa.text("DELETE FROM organizations.audit_log WHERE id = :id"),
            {"id": entry_id},
        )

    assert "append-only" in str(excinfo.value)


async def test_the_table_cannot_be_truncated(db_session: AsyncSession) -> None:
    """TRUNCATE fires no row-level trigger — it needs its own, and has one."""
    # Arrange
    await _one_entry(db_session)

    # Act / Assert
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(sa.text("TRUNCATE organizations.audit_log"))

    assert "append-only" in str(excinfo.value)


async def test_the_actor_and_tenant_carry_no_foreign_key(db_session: AsyncSession) -> None:
    """A cascade or SET NULL here would erase the trail with its subject."""
    # Arrange / Act
    constrained = (
        (
            await db_session.execute(
                sa.text(
                    """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name = tc.constraint_name
                 AND kcu.constraint_schema = tc.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'organizations'
                  AND tc.table_name = 'audit_log'
                """
                )
            )
        )
        .scalars()
        .all()
    )

    # Assert
    assert list(constrained) == []
