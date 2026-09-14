"""Authentication helpers shared by the component and integration tiers.

Minting a real signed JWT (rather than stubbing ``get_current_user_id``) keeps
the token-decode path in the test: a change that breaks claim validation should
turn tests red, not slip past a stub.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from src.core.config import settings
from src.core.ids import uuid7
from src.core.security import TokenType, hash_password
from src.modules.users.models import ROLE_USER, User


def make_access_token(
    user_id: uuid.UUID,
    *,
    issued_at: datetime | None = None,
    expires_in_seconds: int | None = None,
    token_type: str = TokenType.ACCESS.value,
    family_id: uuid.UUID | None = None,
) -> str:
    """Mint a signed access token for a user, with overridable claims.

    Signs with the live settings key so the token is accepted by the real
    :func:`src.core.security.decode_token`.

    Args:
        user_id: The subject the token authenticates.
        issued_at: ``iat`` instant; defaults to now. Backdate it to exercise the
            Redis session-revocation watermark.
        expires_in_seconds: Lifetime from ``issued_at``; defaults to the
            configured access TTL. Pass a negative value for an expired token.
        token_type: The ``type`` claim; override it to prove that a non-access
            token is rejected.
        family_id: The ``fam`` claim — which login lineage this token belongs
            to. Omitted by default, matching a token minted before the claim
            existed; pass it in tests about sessions, where "which one is mine"
            is the question.

    Returns:
        The encoded JWT string.
    """
    now = issued_at or datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds if expires_in_seconds is None else expires_in_seconds
    claims: dict[str, object] = {
        "sub": str(user_id),
        "type": token_type,
        "jti": str(uuid7()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    if family_id is not None:
        claims["fam"] = str(family_id)
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def auth_headers(user_id: uuid.UUID, **token_kwargs: object) -> dict[str, str]:
    """Build the ``Authorization`` header for a user.

    Args:
        user_id: The subject the token authenticates.
        **token_kwargs: Forwarded to :func:`make_access_token`.

    Returns:
        A header mapping ready to hand to an httpx request.
    """
    return {"Authorization": f"Bearer {make_access_token(user_id, **token_kwargs)}"}  # type: ignore[arg-type]


def workspace_headers(user_id: uuid.UUID, workspace_id: uuid.UUID) -> dict[str, str]:
    """Build the auth + tenancy headers a workspace-scoped route requires.

    Args:
        user_id: The authenticated caller.
        workspace_id: The active workspace sent as ``X-Workspace-Id``.

    Returns:
        Both headers in one mapping.
    """
    from src.modules.workspaces.contract import WORKSPACE_HEADER

    return {**auth_headers(user_id), WORKSPACE_HEADER: str(workspace_id)}


#: A bcrypt digest of :data:`KNOWN_PASSWORD`, hashed once per session. Hashing
#: costs ~200 ms by design, so tests that only need *a* valid user reuse this
#: instead of paying for it per test.
KNOWN_PASSWORD = "correct-horse-battery"
_KNOWN_PASSWORD_HASH: str | None = None


def known_password_hash() -> str:
    """Return the cached bcrypt digest of :data:`KNOWN_PASSWORD`."""
    global _KNOWN_PASSWORD_HASH
    if _KNOWN_PASSWORD_HASH is None:
        _KNOWN_PASSWORD_HASH = hash_password(KNOWN_PASSWORD)
    return _KNOWN_PASSWORD_HASH


def make_user(
    *,
    email: str = "tester@example.com",
    role: str = ROLE_USER,
    is_active: bool = True,
    user_id: uuid.UUID | None = None,
    email_confirmed: bool = True,
) -> User:
    """Build an in-memory :class:`User` row (never added to a session here).

    Args:
        email: The account email.
        role: ``user`` or ``dev`` (see :mod:`src.modules.users.models`).
        is_active: Whether the account is enabled.
        user_id: Explicit primary key; a fresh UUIDv7 when omitted.
        email_confirmed: Whether the address has been proven. Defaults to
            ``True`` because that is the state of every account that can
            actually be used — `/login` refuses an unconfirmed one — so a test
            about something else should not have to say so. Pass ``False`` in
            the tests that are ABOUT the unconfirmed state.

    Returns:
        A transient :class:`User` instance with a usable password digest.
    """
    return User(
        id=user_id or uuid7(),
        email=email,
        hashed_password=known_password_hash(),
        is_active=is_active,
        role=role,
        email_confirmed_at=datetime.now(UTC) if email_confirmed else None,
        created_at=datetime.now(UTC),
    )
