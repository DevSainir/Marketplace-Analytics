"""The audit trail, driven through the real routes against a real database.

The table's own guarantees are pinned next door in
``test_audit_log_is_append_only.py``. What is checked here is the half that a
correct table cannot supply on its own: that the routes actually *write*, that
what they write identifies the actor and the tenant, and — the one worth having
a test for — that the credentials these routes hand out never reach the log.

An invitation token and an activation code are both "a thing that buys access",
returned exactly once in a response body and stored hashed everywhere else. An
audit row is readable for as long as the row exists, by anyone who can read the
tenant's trail. A copy of the credential landing there would quietly undo the
hashing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password
from src.modules.organizations.models import MemberRole, Membership, Organization
from src.modules.users.models import ROLE_USER, User

pytestmark = pytest.mark.integration


async def _owner(session: AsyncSession, organization: Organization) -> User:
    """Persist an account owning ``organization``, and return it."""
    user = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("a-long-enough-password"),
        role=ROLE_USER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=MemberRole.OWNER,
        )
    )
    await session.flush()
    return user


def _auth(user: User) -> dict[str, str]:
    """Return an Authorization header carrying a valid access token."""
    token, _ = create_access_token(user_id=user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _isolated_redis(redis_client: Any) -> None:
    """Give every test in this file its own Redis client.

    These requests go through the real app, so ``get_current_user_id`` consults
    the session-revocation watermark on each one. Without a per-test client the
    process-wide one hands the second test connections bound to the first test's
    event loop — "attached to a different loop", a long way from its cause.
    """


async def _entries(session: AsyncSession) -> list[Any]:
    """Return every audit row written so far, oldest first."""
    result = await session.execute(
        sa.text(
            "SELECT event, actor_user_id, actor_email, organization_id, "
            "target_type, target_id, ip_address, metadata "
            "FROM organizations.audit_log ORDER BY id"
        )
    )
    return list(result.all())


async def test_inviting_a_manager_is_recorded_with_its_actor_and_tenant(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The minimum an entry must carry to be worth anything during an incident."""
    # Arrange
    owner = await _owner(db_session, organization)

    # Act
    response = await api_client.post(
        "/api/v1/organizations/invitations",
        json={"email": "colleague@example.com", "valid_for_days": 7},
        headers=_auth(owner),
    )

    # Assert
    assert response.status_code == 201, response.text
    entries = await _entries(db_session)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.event == "MEMBER_INVITED"
    assert entry.actor_user_id == owner.id
    assert entry.actor_email == owner.email
    assert entry.organization_id == organization.id
    assert entry.target_type == "invitation"
    assert entry.target_id == response.json()["id"]


async def test_the_invitation_token_never_reaches_the_audit_log(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The token is a credential shown exactly once; the log is forever."""
    # Arrange
    owner = await _owner(db_session, organization)

    # Act
    response = await api_client.post(
        "/api/v1/organizations/invitations",
        json={"email": "colleague@example.com", "valid_for_days": 7},
        headers=_auth(owner),
    )
    token = response.json()["token"]

    # Assert
    assert token, "the test would be vacuous if no token were issued"
    recorded = str(await _entries(db_session))
    assert token not in recorded


async def test_revoking_an_invitation_is_recorded(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Withdrawing access is exactly the kind of act the trail is kept for."""
    # Arrange
    owner = await _owner(db_session, organization)
    created = await api_client.post(
        "/api/v1/organizations/invitations",
        json={"email": "colleague@example.com", "valid_for_days": 7},
        headers=_auth(owner),
    )
    invitation_id = created.json()["id"]

    # Act
    response = await api_client.delete(
        f"/api/v1/organizations/invitations/{invitation_id}",
        headers=_auth(owner),
    )

    # Assert
    assert response.status_code == 204, response.text
    events = [entry.event for entry in await _entries(db_session)]
    assert events == ["MEMBER_INVITED", "INVITATION_REVOKED"]


async def test_a_rejected_action_records_nothing(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The entry joins the action's transaction, so a 4xx leaves no claim.

    A log that records attempts as though they succeeded is worse than none: it
    reads, later, as evidence that something happened.
    """
    # Arrange
    owner = await _owner(db_session, organization)

    # Act
    response = await api_client.delete(
        f"/api/v1/organizations/invitations/{uuid.uuid4()}",
        headers=_auth(owner),
    )

    # Assert
    assert response.status_code == 404, response.text
    assert await _entries(db_session) == []
