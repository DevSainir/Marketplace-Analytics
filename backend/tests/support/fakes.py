"""In-memory stand-ins for the repository layer.

Used by the **component** tier, where the goal is to exercise the real router →
DI → service wiring without a database. Each fake implements only the methods
its collaborators actually call, and stores rows in plain dicts/lists so a test
can assert on persisted state directly.

These are deliberately hand-written rather than ``MagicMock``: a mock accepts
any call and silently returns a mock, so a renamed repository method keeps the
test green while production breaks. A hand-written fake raises ``AttributeError``
instead — the failure the test exists to catch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.ids import uuid7
from src.modules.users.models import RefreshToken, User
from src.modules.workspaces.models import Workspace, WorkspaceToken


class FakeUserRepository:
    """In-memory :class:`~src.modules.users.repos.UserRepository`."""

    def __init__(self, users: list[User] | None = None) -> None:
        """Seed the store with optional pre-existing users."""
        self.users: dict[uuid.UUID, User] = {user.id: user for user in users or []}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with this primary key, or ``None``."""
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this exact (already normalized) email."""
        return next((user for user in self.users.values() if user.email == email), None)

    async def create(self, *, email: str, hashed_password: str) -> User:
        """Insert and return a new user row."""
        user = User(
            id=uuid7(),
            email=email,
            hashed_password=hashed_password,
            is_active=True,
            role="user",
            created_at=datetime.now(UTC),
        )
        self.users[user.id] = user
        return user


class FakeRefreshTokenRepository:
    """In-memory :class:`~src.modules.users.repos.RefreshTokenRepository`."""

    def __init__(self) -> None:
        """Start with an empty token store."""
        self.tokens: dict[uuid.UUID, RefreshToken] = {}

    async def create(
        self,
        *,
        token_id: uuid.UUID,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        parent_id: uuid.UUID | None = None,
    ) -> RefreshToken:
        """Persist a newly issued refresh-token row."""
        token = RefreshToken(
            id=token_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
            parent_id=parent_id,
            is_used=False,
            is_revoked=False,
            created_at=datetime.now(UTC),
        )
        self.tokens[token_id] = token
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Return the token row carrying this secret digest, or ``None``."""
        return next((t for t in self.tokens.values() if t.token_hash == token_hash), None)

    async def consume(self, token_id: uuid.UUID) -> bool:
        """Flag a token consumed exactly once, mirroring the conditional UPDATE."""
        token = self.tokens.get(token_id)
        if token is None or token.is_used:
            return False
        token.is_used = True
        return True

    async def family_started_at(self, family_id: uuid.UUID) -> datetime | None:
        """Return the earliest issuance instant in a login family."""
        stamps = [t.created_at for t in self.tokens.values() if t.family_id == family_id]
        return min(stamps) if stamps else None

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke every live token in one login lineage; return the count."""
        revoked = 0
        for token in self.tokens.values():
            if token.family_id == family_id and not token.is_revoked:
                token.is_revoked = True
                revoked += 1
        return revoked

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke every live token owned by a user; return the count."""
        revoked = 0
        for token in self.tokens.values():
            if token.user_id == user_id and not token.is_revoked:
                token.is_revoked = True
                revoked += 1
        return revoked

    async def delete_expired(self, *, before: datetime) -> int:
        """Hard-delete rows that expired before the cutoff; return the count."""
        stale = [tid for tid, t in self.tokens.items() if t.expires_at < before]
        for token_id in stale:
            del self.tokens[token_id]
        return len(stale)


class FakeWorkspaceRepository:
    """In-memory :class:`~src.modules.workspaces.repos.WorkspaceRepository`."""

    def __init__(self, workspaces: list[Workspace] | None = None) -> None:
        """Seed the store with optional pre-existing workspaces."""
        self.workspaces: dict[uuid.UUID, Workspace] = {ws.id: ws for ws in workspaces or []}

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        """Return the workspace with this id, or ``None``."""
        return self.workspaces.get(workspace_id)

    async def get_by_name(self, name: str) -> Workspace | None:
        """Return the workspace with this exact name, or ``None``."""
        return next((ws for ws in self.workspaces.values() if ws.name == name), None)

    async def list_all(self) -> list[Workspace]:
        """Return every workspace across every tenant, oldest first."""
        return sorted(self.workspaces.values(), key=lambda ws: ws.created_at)

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Workspace]:
        """Return one organisation's workspaces, oldest first."""
        return sorted(
            (ws for ws in self.workspaces.values() if ws.organization_id == organization_id),
            key=lambda ws: ws.created_at,
        )

    async def count_for_organization(self, organization_id: uuid.UUID) -> int:
        """Count one organisation's workspaces."""
        return sum(1 for ws in self.workspaces.values() if ws.organization_id == organization_id)

    async def create(self, *, organization_id: uuid.UUID, name: str) -> Workspace:
        """Insert and return a new, non-primary workspace in one organisation."""
        workspace = Workspace(
            id=uuid7(),
            organization_id=organization_id,
            name=name,
            is_primary=False,
            created_at=datetime.now(UTC),
        )
        self.workspaces[workspace.id] = workspace
        return workspace

    async def delete(self, workspace: Workspace) -> None:
        """Remove a workspace from the store."""
        self.workspaces.pop(workspace.id, None)


class FakeWorkspaceTokenRepository:
    """In-memory :class:`~src.modules.workspaces.repos.WorkspaceTokenRepository`.

    Stores exactly what production stores — the *ciphertext* — so a test can
    assert that no plaintext WB token ever reaches the persistence layer.
    """

    def __init__(self) -> None:
        """Start with an empty token store keyed by ``(workspace_id, kind)``."""
        self.rows: dict[tuple[uuid.UUID, str], WorkspaceToken] = {}

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[WorkspaceToken]:
        """Return every stored token row of one workspace."""
        return [row for (ws_id, _), row in self.rows.items() if ws_id == workspace_id]

    async def list_all(self) -> list[WorkspaceToken]:
        """Return every stored token row across all workspaces."""
        return list(self.rows.values())

    async def upsert(
        self, *, workspace_id: uuid.UUID, kind: str, token_encrypted: str
    ) -> WorkspaceToken:
        """Insert or rotate one workspace/kind token."""
        row = WorkspaceToken(
            id=uuid7(),
            workspace_id=workspace_id,
            kind=kind,
            token_encrypted=token_encrypted,
            updated_at=datetime.now(UTC),
        )
        self.rows[(workspace_id, kind)] = row
        return row

    async def delete_kind(self, *, workspace_id: uuid.UUID, kind: str) -> None:
        """Delete one workspace/kind token if it exists."""
        self.rows.pop((workspace_id, kind), None)


def make_workspace(
    *,
    organization_id: uuid.UUID,
    name: str = "ИП Тестовый",
    is_primary: bool = False,
    workspace_id: uuid.UUID | None = None,
) -> Workspace:
    """Build a transient :class:`Workspace` row.

    Args:
        organization_id: The owning tenant. Required, with no default, because
            the request path now compares it against the caller's own
            organisation — a fake that invented one would make every tenancy
            test pass for the wrong reason.
        name: Display name (unique in production).
        is_primary: Primary workspaces store one token per WB category;
            every other workspace stores a single ``unified`` token.
        workspace_id: Explicit primary key; a fresh UUIDv7 when omitted.

    Returns:
        An unsaved :class:`Workspace` instance.
    """
    return Workspace(
        id=workspace_id or uuid7(),
        organization_id=organization_id,
        name=name,
        is_primary=is_primary,
        created_at=datetime.now(UTC),
    )


class FakeLoginBackoff:
    """In-memory stand-in for the per-account login backoff.

    Same surface as :class:`~src.modules.users.services.lockout.LoginBackoff`,
    counting in a dict instead of Redis. It exists so the unit tier can drive
    :class:`~src.modules.users.services.auth.AuthService` without a socket, and
    so a test can put an account into backoff by simply setting
    :attr:`penalty`.

    Attributes:
        penalty: Seconds :meth:`penalty_remaining` reports for every account.
        failures: Per-email count of :meth:`record_failure` calls.
        cleared: Emails :meth:`clear` was called for, in order.
    """

    def __init__(self, *, penalty: int = 0) -> None:
        """Start with no account in backoff unless one is asked for."""
        self.penalty = penalty
        self.failures: dict[str, int] = {}
        self.cleared: list[str] = []

    async def penalty_remaining(self, *, email: str) -> int:
        """Report the configured penalty for any account."""
        return self.penalty

    async def record_failure(self, *, email: str) -> None:
        """Count one failed attempt against this account."""
        self.failures[email] = self.failures.get(email, 0) + 1

    async def clear(self, *, email: str) -> None:
        """Forget this account's failures."""
        self.cleared.append(email)
        self.failures.pop(email, None)


class FakePasswordBreachCheck:
    """In-memory stand-in for the Have I Been Pwned range query.

    Same surface as
    :class:`~src.integrations.pwned.PasswordBreachCheck`, answering from a set
    instead of the network.

    Attributes:
        breached: Passwords this fake reports as already public.
        asked: Every password it was asked about, in order.
    """

    def __init__(self, *, breached: set[str] | None = None) -> None:
        """Start with nothing breached unless told otherwise."""
        self.breached = breached or set()
        self.asked: list[str] = []

    async def is_breached(self, password: str) -> bool:
        """Report whether this password is in the configured set."""
        self.asked.append(password)
        return password in self.breached
