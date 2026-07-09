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

import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    TokenReuseError,
)
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.core.redis import mark_user_sessions_revoked
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


def _normalize_email(email: str) -> str:
    """Canonicalize an email for storage and lookup.

    Lowercasing the whole address means ``User@X.com`` and ``user@x.com`` are
    one account: without it, case-variant duplicates register freely and users
    who typed mixed case at signup fail later logins. (RFC 5321 technically
    allows a case-sensitive local part; in practice no mainstream provider is,
    and login ergonomics win.)
    """
    return email.strip().lower()


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
    async def register(self, *, email: str, password: str, invite_code: str) -> UserRead:
        """Register a new user account (invite-gated).

        The platform is single-tenant: every authenticated account can read the
        seller's business data, so open registration would hand that data to
        anyone on the internet. A valid invite code (operator-configured) is
        therefore required; an empty configured code disables registration.

        Args:
            email: Desired unique login email (normalized to lowercase).
            password: Plaintext password (hashed before persistence).
            invite_code: The registration invite code presented by the client.

        Returns:
            The newly created account as a :class:`UserRead` DTO (the router
            returns it verbatim — no presentation-layer mapping needed).

        Raises:
            PermissionDeniedError: If registration is disabled or the invite
                code does not match.
            ConflictError: If the email is already registered.
        """
        configured = settings.registration_invite_code
        # compare_digest keeps the check constant-time so the code cannot be
        # guessed byte-by-byte via response latency.
        if not configured or not secrets.compare_digest(invite_code, configured):
            raise PermissionDeniedError("Registration is by invitation only.")

        email = _normalize_email(email)
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise ConflictError("A user with this email already exists.")
        hashed = await asyncio.to_thread(hash_password, password)
        try:
            user = await self._users.create(email=email, hashed_password=hashed)
        except IntegrityError as exc:
            # Two concurrent registrations for the same email both pass the
            # pre-check; the unique index catches the loser here. Map it to the
            # same 409 as the fast path instead of leaking a raw 500.
            raise ConflictError("A user with this email already exists.") from exc
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
                account (deliberately the same message for all three, so the
                response is not an account-existence oracle).
        """
        user = await self._users.get_by_email(_normalize_email(email))

        # bcrypt is CPU-bound (~100-300 ms); to_thread keeps the event loop
        # serving other requests instead of stalling the whole process.
        if user is None:
            # Burn an equivalent bcrypt cycle to equalise timing, then fail.
            await asyncio.to_thread(verify_password, password, DUMMY_HASH)
            raise AuthenticationError("Invalid email or password.")

        if not await asyncio.to_thread(verify_password, password, user.hashed_password):
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            logger.info("Login attempt for disabled account %s.", user.id)
            raise AuthenticationError("Invalid email or password.")

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
                expired, the account is no longer active, or the session's
                absolute lifetime is exhausted.
            TokenReuseError: If a consumed token is replayed (breach).
        """
        if not refresh_secret:
            raise AuthenticationError("Missing refresh token.")
        token = await self._tokens.get_by_hash(hash_refresh_secret(refresh_secret))
        if token is None:
            raise AuthenticationError("Invalid refresh token.")

        # --- Breach (fast path): a consumed token is being replayed. ---
        if token.is_used:
            await self._revoke_breached_user(user_id=token.user_id, family_id=token.family_id)
            raise TokenReuseError("Refresh token reuse detected. All sessions have been revoked.")

        if token.is_revoked:
            raise AuthenticationError("This session has been revoked.")

        now = datetime.now(UTC)
        if token.expires_at <= now:
            raise AuthenticationError("Refresh token has expired.")

        # Rotation must re-check the account, not just the token row: a
        # disabled user holding a valid refresh cookie would otherwise keep
        # renewing 7-day sessions forever.
        user = await self._users.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("This account is disabled.")

        # Absolute ceiling per login lineage: rotation slides the refresh
        # window, but a family may not outlive the configured session lifetime.
        family_started = await self._tokens.family_started_at(token.family_id) or now
        session_deadline = family_started + timedelta(
            seconds=settings.session_absolute_lifetime_seconds
        )
        if session_deadline <= now:
            raise AuthenticationError("Session lifetime exceeded. Please log in again.")

        # --- Breach (race path): consume the token atomically. If another
        # request already consumed it between our read and this UPDATE, this is
        # the same replay situation as the fast path above — without the
        # conditional consume, two concurrent presentations of a stolen secret
        # would BOTH rotate successfully and the theft would go undetected.
        if not await self._tokens.consume(token.id):
            await self._revoke_breached_user(user_id=token.user_id, family_id=token.family_id)
            raise TokenReuseError("Refresh token reuse detected. All sessions have been revoked.")

        return await self._issue_pair(
            user_id=token.user_id,
            family_id=token.family_id,
            parent_id=token.id,
            not_after=session_deadline,
        )

    async def _revoke_breached_user(self, *, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
        """Kill every session of a user whose refresh token was replayed.

        Revokes all refresh rows in a DEDICATED committed transaction: the
        calling request ends in a 401 (an exception), which rolls back the
        request-scoped session — so the revocation must persist independently
        or the "log out all devices" guarantee would be silently undone. Also
        stamps the Redis watermark so outstanding *access* tokens die
        immediately instead of surviving until natural expiry.
        """
        logger.warning(
            "Refresh-token reuse detected for user %s (family %s); revoking all sessions.",
            user_id,
            family_id,
        )
        async with AsyncSessionLocal() as breach_session:
            await RefreshTokenRepository(breach_session).revoke_all_for_user(user_id)
            await breach_session.commit()
        await mark_user_sessions_revoked(user_id)

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
        not_after: datetime | None = None,
    ) -> IssuedTokens:
        """Create and persist a new access+refresh pair for one user.

        Args:
            user_id: The subject user's id.
            family_id: The login-lineage identifier to attach the token to.
            parent_id: The superseded token id, or ``None`` for a fresh login.
            not_after: Optional absolute ceiling for the refresh expiry (the
                family's session-lifetime deadline); the sliding TTL is
                clamped to it so rotation cannot extend a session forever.

        Returns:
            The issued token bundle including cookie-ready expiry metadata.
        """
        token_id = uuid7()
        access_token, access_expires_at = create_access_token(user_id=user_id, jti=token_id)

        refresh_secret = generate_refresh_secret()
        refresh_expires_at = datetime.now(UTC) + timedelta(
            seconds=settings.refresh_token_ttl_seconds
        )
        if not_after is not None:
            refresh_expires_at = min(refresh_expires_at, not_after)

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
