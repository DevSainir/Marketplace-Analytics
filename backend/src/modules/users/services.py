"""Business logic for authentication and JWT session rotation.

This service orchestrates the security primitives from :mod:`src.core.security`
and the persistence primitives from :mod:`src.modules.users.repos`. It contains
**no** SQL and **no** HTTP handling — it raises semantic
:mod:`src.core.exceptions` errors that the router maps to HTTP responses.

Key security behaviours implemented here:

* **Refresh Token Rotation (RTR):** every refresh consumes the presented token
  and issues a brand-new access+refresh pair.
* **Breach detection:** replay of an already-consumed token revokes the user's
  entire active session set and raises :class:`TokenReuseError` (HTTP 401).
* **Timing-attack mitigation:** unknown-user logins still run a bcrypt verify
  against :data:`DUMMY_HASH`, keeping response latency constant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import (
    AuthenticationError,
    ConflictError,
    TokenReuseError,
)
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.core.security import (
    DUMMY_HASH,
    create_access_token,
    generate_refresh_secret,
    hash_password,
    hash_refresh_secret,
    verify_password,
)
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.schemas import IssuedTokens, UserRead

logger = get_logger(__name__)


class AuthService:
    """Coordinates registration, login, refresh rotation, and logout."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        token_repo: RefreshTokenRepository,
    ) -> None:
        """Inject the collaborating repositories.

        Args:
            user_repo: Repository for :class:`User` persistence.
            token_repo: Repository for :class:`RefreshToken` persistence.
        """
        self._users = user_repo
        self._tokens = token_repo

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    async def register(self, *, email: str, password: str) -> UserRead:
        """Register a new user account.

        Args:
            email: Desired unique login email.
            password: Plaintext password (hashed before persistence).

        Returns:
            The newly created account as a :class:`UserRead` DTO (the router
            returns it verbatim — no presentation-layer mapping needed).

        Raises:
            ConflictError: If the email is already registered.
        """
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise ConflictError("A user with this email already exists.")
        user = await self._users.create(email=email, hashed_password=hash_password(password))
        return UserRead.model_validate(user)

    # ------------------------------------------------------------------ #
    # Login (with timing-attack mitigation)
    # ------------------------------------------------------------------ #
    async def authenticate(self, *, email: str, password: str) -> IssuedTokens:
        """Authenticate credentials and issue a fresh token pair.

        The lookup path is deliberately constant-time: when the email is
        unknown we still execute a bcrypt verification against
        :data:`DUMMY_HASH` before failing, so an attacker cannot distinguish
        "no such user" from "wrong password" by measuring latency.

        Args:
            email: Submitted login email.
            password: Submitted plaintext password.

        Returns:
            A fresh :class:`IssuedTokens` bundle.

        Raises:
            AuthenticationError: On unknown user, wrong password, or inactive
                account.
        """
        user = await self._users.get_by_email(email)

        if user is None:
            # Burn an equivalent bcrypt cycle to equalise timing, then fail.
            verify_password(password, DUMMY_HASH)
            raise AuthenticationError("Invalid email or password.")

        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        # A fresh login opens a new token family/lineage.
        return await self._issue_pair(user_id=user.id, family_id=uuid7(), parent_id=None)

    # ------------------------------------------------------------------ #
    # Refresh rotation (with breach detection)
    # ------------------------------------------------------------------ #
    async def rotate_refresh_token(self, *, refresh_secret: str | None) -> IssuedTokens:
        """Rotate a presented refresh token into a brand-new pair.

        Implements the Breach Detection Flow: if the presented token has already
        been consumed (``is_used is True``), the whole user session set is
        revoked and a :class:`TokenReuseError` (HTTP 401) is raised.

        Args:
            refresh_secret: The opaque refresh secret from the client cookie, or
                ``None`` when the cookie is absent (treated as unauthorized).

        Returns:
            A freshly issued :class:`IssuedTokens` bundle continuing the family.

        Raises:
            AuthenticationError: If the token is missing, unknown, revoked, or
                expired.
            TokenReuseError: If a consumed token is replayed (breach).
        """
        if not refresh_secret:
            raise AuthenticationError("Missing refresh token.")
        token = await self._tokens.get_by_hash(hash_refresh_secret(refresh_secret))
        if token is None:
            raise AuthenticationError("Invalid refresh token.")

        # --- Breach: a consumed token is being replayed. ---
        if token.is_used:
            logger.warning(
                "Refresh-token reuse detected for user %s (family %s); revoking all sessions.",
                token.user_id,
                token.family_id,
            )
            # Revoke in a DEDICATED committed transaction: this request returns
            # 401 (an exception), which rolls back the request-scoped session —
            # so the revocation must persist independently or the "log out all
            # devices" guarantee would be silently undone.
            async with AsyncSessionLocal() as breach_session:
                await RefreshTokenRepository(breach_session).revoke_all_for_user(token.user_id)
                await breach_session.commit()
            raise TokenReuseError("Refresh token reuse detected. All sessions have been revoked.")

        if token.is_revoked:
            raise AuthenticationError("This session has been revoked.")

        if token.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Refresh token has expired.")

        # Consume the current token, then mint its child in the same family.
        await self._tokens.mark_used(token.id)
        return await self._issue_pair(
            user_id=token.user_id,
            family_id=token.family_id,
            parent_id=token.id,
        )

    # ------------------------------------------------------------------ #
    # Logout
    # ------------------------------------------------------------------ #
    async def logout(self, *, refresh_secret: str | None) -> None:
        """Revoke the family associated with a presented refresh token.

        Silent no-op for a missing or unknown token so logout is idempotent and
        cannot be used as a user/token enumeration oracle.

        Args:
            refresh_secret: The opaque refresh secret from the client cookie, or
                ``None`` when the cookie is absent.
        """
        if not refresh_secret:
            return
        token = await self._tokens.get_by_hash(hash_refresh_secret(refresh_secret))
        if token is not None:
            await self._tokens.revoke_family(token.family_id)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _issue_pair(
        self,
        *,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        parent_id: uuid.UUID | None,
    ) -> IssuedTokens:
        """Create and persist a new access+refresh pair for one user.

        Args:
            user_id: The subject user's id.
            family_id: The login-lineage identifier to attach the token to.
            parent_id: The superseded token id, or ``None`` for a fresh login.

        Returns:
            The issued token bundle including cookie-ready expiry metadata.
        """
        token_id = uuid7()
        access_token, access_expires_at = create_access_token(user_id=user_id, jti=token_id)

        refresh_secret = generate_refresh_secret()
        refresh_expires_at = datetime.now(UTC) + timedelta(
            seconds=settings.refresh_token_ttl_seconds
        )

        await self._tokens.create(
            token_id=token_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_refresh_secret(refresh_secret),
            expires_at=refresh_expires_at,
            parent_id=parent_id,
        )

        return IssuedTokens(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_secret=refresh_secret,
            refresh_expires_at=refresh_expires_at,
        )
