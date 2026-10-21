"""Every change to a subscription term lands in the audit log — whoever makes it.

Born of an incident on 2026-10-06: a hand renewal done as a bare ``UPDATE`` in psql left
``updated_at`` at the activation day and wrote no audit row, so when the term
ran out the database could not say it had ever been extended. The record is a
trigger so that the psql path is covered too; these tests therefore go around
the ORM and issue the SQL directly, the way that renewal was done.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.repos import OrganizationRepository, SubscriptionRepository
from src.modules.organizations.services.renewal import extend_subscription

pytestmark = pytest.mark.integration

EXPIRES = datetime(2026, 10, 5, 6, 27, tzinfo=UTC)


async def _subscription(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist an organisation with a term ending at :data:`EXPIRES`."""
    org = await OrganizationRepository(session).create(name="owner@example.com")
    sub = await SubscriptionRepository(session).create(
        organization_id=org.id,
        started_at=EXPIRES - timedelta(days=14),
        expires_at=EXPIRES,
        grace_days=3,
    )
    return org.id, sub.id


async def _trail(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[sa.Row[tuple[object, ...]]]:
    """The organisation's SUBSCRIPTION_CHANGED entries, oldest first."""
    result = await session.execute(
        sa.text(
            "SELECT actor_email, target_id, metadata FROM organizations.audit_log "
            "WHERE organization_id = :org AND event = 'SUBSCRIPTION_CHANGED' "
            "ORDER BY occurred_at"
        ),
        {"org": organization_id},
    )
    return list(result.all())


async def test_a_raw_sql_extension_is_recorded_with_before_and_after(
    db_session: AsyncSession,
) -> None:
    """The psql renewal that left no trace now leaves one, marked as unattributed."""
    org_id, sub_id = await _subscription(db_session)

    await db_session.execute(
        sa.text(
            "UPDATE organizations.subscriptions "
            "SET expires_at = expires_at + interval '14 days' WHERE id = :id"
        ),
        {"id": sub_id},
    )

    [entry] = await _trail(db_session, org_id)
    assert entry.actor_email is None
    assert entry.target_id == str(sub_id)
    assert entry.metadata["operation"] == "update"
    assert entry.metadata["source"] == "sql"
    assert datetime.fromisoformat(entry.metadata["previous_expires_at"]) == EXPIRES
    assert datetime.fromisoformat(entry.metadata["expires_at"]) == EXPIRES + timedelta(days=14)


async def test_a_raw_sql_change_moves_updated_at(db_session: AsyncSession) -> None:
    """``updated_at`` stops claiming the term was last touched at activation."""
    _, sub_id = await _subscription(db_session)
    await db_session.execute(
        sa.text("UPDATE organizations.subscriptions SET updated_at = :old WHERE id = :id"),
        {"old": EXPIRES - timedelta(days=30), "id": sub_id},
    )

    await db_session.execute(
        sa.text("UPDATE organizations.subscriptions SET grace_days = 7 WHERE id = :id"),
        {"id": sub_id},
    )

    updated_at = (
        await db_session.execute(
            sa.text("SELECT updated_at FROM organizations.subscriptions WHERE id = :id"),
            {"id": sub_id},
        )
    ).scalar_one()
    assert updated_at > EXPIRES


async def test_the_renewal_path_records_who_extended(db_session: AsyncSession) -> None:
    """With ``app.audit_actor`` set, as the renewal script sets it, the actor is named."""
    org_id, _ = await _subscription(db_session)
    sub = await SubscriptionRepository(db_session).get_for_organization(org_id)
    assert sub is not None
    await db_session.execute(
        sa.select(sa.func.set_config("app.audit_actor", "dev@example.com", True))
    )

    await extend_subscription(
        SubscriptionRepository(db_session), sub, days=14, now=EXPIRES + timedelta(days=1)
    )

    [entry] = await _trail(db_session, org_id)
    assert entry.actor_email == "dev@example.com"
    assert entry.metadata["source"] == "tool"
    assert datetime.fromisoformat(entry.metadata["expires_at"]) == EXPIRES + timedelta(days=14)


async def test_an_update_that_changes_nothing_is_not_recorded(db_session: AsyncSession) -> None:
    """A no-op write would bury the real renewals in noise."""
    org_id, sub_id = await _subscription(db_session)

    await db_session.execute(
        sa.text("UPDATE organizations.subscriptions SET expires_at = expires_at WHERE id = :id"),
        {"id": sub_id},
    )

    assert await _trail(db_session, org_id) == []


async def test_deleting_a_term_is_recorded(db_session: AsyncSession) -> None:
    """Removing a subscription closes the service; that must not be silent either."""
    org_id, sub_id = await _subscription(db_session)

    await db_session.execute(
        sa.text("DELETE FROM organizations.subscriptions WHERE id = :id"), {"id": sub_id}
    )

    [entry] = await _trail(db_session, org_id)
    assert entry.metadata["operation"] == "delete"
    assert datetime.fromisoformat(entry.metadata["previous_expires_at"]) == EXPIRES
    assert "expires_at" not in entry.metadata
