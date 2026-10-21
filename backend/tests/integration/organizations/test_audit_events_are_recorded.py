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
from datetime import UTC, datetime
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
        # Confirmed: `/login` refuses an unproven address, so an account a
        # test authenticates as has to be one.
        email_confirmed_at=datetime.now(UTC),
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
    """Return every route-written audit row so far, oldest first.

    ``SUBSCRIPTION_CHANGED`` is left out: a database trigger writes it, and the
    race tests in this directory commit for real and clean up by deleting their
    organisations, so the cascade leaves one such row behind in the test
    database for good — the table refuses to forget, which is its point. That
    trail is pinned in ``test_subscription_change_trail.py``.
    """
    result = await session.execute(
        sa.text(
            "SELECT event, actor_user_id, actor_email, organization_id, "
            "target_type, target_id, ip_address, metadata "
            "FROM organizations.audit_log "
            "WHERE event <> 'SUBSCRIPTION_CHANGED' ORDER BY id"
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


async def _manager(session: AsyncSession, organization: Organization) -> User:
    """Persist a manager of ``organization`` with the default full grant."""
    user = User(
        email=f"manager-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("a-long-enough-password"),
        email_confirmed_at=datetime.now(UTC),
        role=ROLE_USER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=MemberRole.MANAGER,
            access_level="read_write",
            modules=["monitoring", "finreports", "ab_tests"],
        )
    )
    await session.flush()
    return user


async def test_re_saving_the_same_grant_records_nothing(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Opening the access form and pressing save is not a change.

    The trail is read to answer «who changed what». An entry saying «Изменён
    доступ» about a grant that is byte-for-byte what it was turns a list meant
    to be read into one that has to be searched.
    """
    # Arrange
    owner = await _owner(db_session, organization)
    manager = await _manager(db_session, organization)

    # Act — the exact grant the manager already holds.
    response = await api_client.patch(
        f"/api/v1/organizations/members/{manager.id}/access",
        json={"access_level": "read_write", "modules": ["monitoring", "finreports", "ab_tests"]},
        headers=_auth(owner),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert await _entries(db_session) == []


async def test_a_real_change_of_grant_is_recorded_with_both_states(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """And a real change still records — with what it was, and who it was about."""
    # Arrange
    owner = await _owner(db_session, organization)
    manager = await _manager(db_session, organization)

    # Act
    response = await api_client.patch(
        f"/api/v1/organizations/members/{manager.id}/access",
        json={"access_level": "read_only", "modules": ["finreports"]},
        headers=_auth(owner),
    )

    # Assert
    assert response.status_code == 200, response.text
    entries = await _entries(db_session)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.event == "MEMBER_ACCESS_CHANGED"
    assert entry.metadata["email"] == manager.email
    assert entry.metadata["access_level"] == "read_only"
    assert entry.metadata["modules"] == ["finreports"]
    assert entry.metadata["previous_access_level"] == "read_write"


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


# --------------------------------------------------------------------------- #
# Reading the trail back — the half that was missing until the route existed
# --------------------------------------------------------------------------- #
async def test_an_owner_can_read_their_own_trail(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """Until this route existed the trail was write-only from the product's view.

    The rows were there and enforced append-only, and the only way to read them
    was psql on the box — a fine answer for us at 02:00 and no answer at all for
    an owner asking who removed a manager.
    """
    # Arrange
    owner = await _owner(db_session, organization)
    await api_client.post(
        "/api/v1/organizations/invitations",
        json={"email": "colleague@example.com", "valid_for_days": 7},
        headers=_auth(owner),
    )

    # Act
    response = await api_client.get("/api/v1/organizations/audit-log", headers=_auth(owner))

    # Assert
    assert response.status_code == 200, response.text
    entries = response.json()
    assert [e["event"] for e in entries] == ["MEMBER_INVITED"]
    assert entries[0]["actor_email"] == owner.email
    assert entries[0]["target_type"] == "invitation"


async def test_the_trail_never_shows_another_organisations_entries(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The one mistake worth designing out of an audit trail.

    The foreign tenant is just a UUID, which is possible only because this
    table deliberately carries no foreign key on `organization_id` — the same
    denormalisation that lets an entry outlive the organisation it describes.
    """
    # Arrange — an entry belonging to somebody else, written directly.
    owner = await _owner(db_session, organization)
    foreign_organization_id = uuid.uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO organizations.audit_log (id, event, organization_id, actor_email) "
            "VALUES (gen_random_uuid(), 'MEMBER_REMOVED', :org, 'other@example.com')"
        ),
        {"org": foreign_organization_id},
    )
    await db_session.flush()

    # Act
    response = await api_client.get("/api/v1/organizations/audit-log", headers=_auth(owner))

    # Assert
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_the_token_a_route_issued_is_not_readable_through_the_trail(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """The write side promises it; this checks the read side cannot undo it.

    An invitation token is shown exactly once in the response that creates it.
    If one reached an audit row, this endpoint would hand it back for as long as
    the row exists — which is the whole point of the "never the secret" rule.
    """
    # Arrange
    owner = await _owner(db_session, organization)
    created = await api_client.post(
        "/api/v1/organizations/invitations",
        json={"email": "colleague@example.com", "valid_for_days": 7},
        headers=_auth(owner),
    )
    token = created.json()["token"]

    # Act
    response = await api_client.get("/api/v1/organizations/audit-log", headers=_auth(owner))

    # Assert
    assert token, "the test would be vacuous if no token were issued"
    assert token not in response.text


async def test_the_page_size_is_bounded(
    api_client: Any,
    db_session: AsyncSession,
    organization: Organization,
) -> None:
    """This is the one table that only ever grows, so an unbounded read ages badly."""
    # Arrange
    owner = await _owner(db_session, organization)

    # Act
    response = await api_client.get(
        "/api/v1/organizations/audit-log?limit=5000", headers=_auth(owner)
    )

    # Assert
    assert response.status_code == 422
