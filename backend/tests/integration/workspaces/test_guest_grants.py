"""Guest grants against a real PostgreSQL.

What only a real database proves: the grant is idempotent under the unique
constraint (``ON CONFLICT DO NOTHING``), granting promotes an ordinary account
to ``head`` and leaves a dev alone, and revoking removes exactly one row.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.organizations.models import Organization
from src.modules.users.models import User
from src.modules.workspaces.guests import (
    grant_guest,
    list_grantable_workspaces,
    list_guests,
    revoke_guest,
)
from src.modules.workspaces.models import Workspace
from src.modules.workspaces.repos import WorkspaceGuestRepository


@pytest.fixture
async def via(db_session: AsyncSession, organization: Organization) -> Workspace:
    """Another company's workspace."""
    workspace = Workspace(organization_id=organization.id, name="NEVA")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def _account(db_session: AsyncSession, email: str, role: str = "user") -> User:
    user = User(email=email, hashed_password="x", role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_granting_opens_the_workspace_and_promotes_to_head(
    db_session: AsyncSession, via: Workspace
) -> None:
    """One call does the whole job: the grant row and the role."""
    # Arrange
    head = await _account(db_session, "head@example.com")

    # Act
    grant = await grant_guest(
        db_session, email="Head@Example.com ", workspace_name="NEVA", granted_by=uuid.uuid4()
    )

    # Assert
    await db_session.refresh(head)
    assert head.role == "head"
    assert grant.workspace_id == via.id
    assert await WorkspaceGuestRepository(db_session).exists(workspace_id=via.id, user_id=head.id)


async def test_granting_twice_keeps_one_grant(db_session: AsyncSession, via: Workspace) -> None:
    """A repeated grant returns the standing one rather than failing."""
    # Arrange
    await _account(db_session, "head@example.com")
    first = await grant_guest(
        db_session, email="head@example.com", workspace_name="NEVA", granted_by=uuid.uuid4()
    )

    # Act
    second = await grant_guest(
        db_session, email="head@example.com", workspace_name="NEVA", granted_by=uuid.uuid4()
    )

    # Assert
    assert second.id == first.id
    count = await db_session.scalar(sa.text("SELECT count(*) FROM workspaces.workspace_guests"))
    assert count == 1


async def test_a_dev_is_refused_and_keeps_the_dev_role(
    db_session: AsyncSession, via: Workspace
) -> None:
    """The wider role is never narrowed by a grant."""
    # Arrange
    dev = await _account(db_session, "dev@example.com", role="dev")

    # Act / Assert
    with pytest.raises(ConflictError):
        await grant_guest(
            db_session, email="dev@example.com", workspace_name="NEVA", granted_by=uuid.uuid4()
        )
    await db_session.refresh(dev)
    assert dev.role == "dev"


async def test_an_unknown_workspace_changes_no_role(
    db_session: AsyncSession, via: Workspace
) -> None:
    """The workspace is checked before the account is promoted."""
    # Arrange
    user = await _account(db_session, "head@example.com")

    # Act / Assert
    with pytest.raises(NotFoundError):
        await grant_guest(
            db_session, email="head@example.com", workspace_name="NOPE", granted_by=uuid.uuid4()
        )
    await db_session.refresh(user)
    assert user.role == "user"


async def test_revoking_removes_the_grant(db_session: AsyncSession, via: Workspace) -> None:
    """After revocation the listing is empty and the lookup says no."""
    # Arrange
    head = await _account(db_session, "head@example.com")
    grant = await grant_guest(
        db_session, email="head@example.com", workspace_name="NEVA", granted_by=uuid.uuid4()
    )

    # Act
    revoked_for = await revoke_guest(db_session, grant.id)

    # Assert
    assert revoked_for == head.id
    assert await list_guests(db_session) == []
    with pytest.raises(NotFoundError):
        await revoke_guest(db_session, grant.id)


async def test_the_grant_form_offers_every_workspace_by_name(
    db_session: AsyncSession, organization: Organization, via: Workspace
) -> None:
    """Across companies, sorted by name regardless of case."""
    # Arrange
    other = Workspace(organization_id=organization.id, name="aлфавит")
    db_session.add(other)
    await db_session.flush()

    # Act
    options = await list_grantable_workspaces(db_session)

    # Assert
    names = [option.name for option in options]
    assert {"NEVA", "aлфавит"} <= set(names)
    assert names == sorted(names, key=str.lower)
