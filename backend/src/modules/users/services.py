"""Business logic for authentication and JWT session rotation.

This service orchestrates the security primitives from :mod:`src.core.security`
and the persistence primitives from :mod:`src.modules.users.repos`. It contains
**no** SQL and **no** HTTP handling — it raises semantic
:mod:`src.core.exceptions` errors that the router maps to HTTP responses.

Key security behaviours implemented here:

* **Refresh Token Rotation (RTR):** every refresh consumes the presented token
  and issues a brand-new access+refresh pair.
* **Breach detection:** replay of an already-consumed token revokes that
  token's family (login lineage) and raises :class:`TokenReuseError` (HTTP 401).
* **Timing-attack mitigation:** unknown-user logins still run a bcrypt verify
  against :data:`DUMMY_HASH`, keeping response latency constant.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

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
        # guessed byte-by-byte via response latency. Compare the UTF-8 ENCODINGS,
        # not the strings: on `str` inputs compare_digest requires both operands
        # to be ASCII-only and raises TypeError otherwise, so a submitted code
        # containing any non-ASCII character (e.g. Cyrillic) turned this check
        # into an unauthenticated 500. `bytes` carries no such restriction.
        if not configured or not secrets.compare_digest(
            invite_code.encode("utf-8"), configured.encode("utf-8")
        ):
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
            await self._revoke_breached_family(user_id=token.user_id, family_id=token.family_id)
            raise TokenReuseError("Refresh token reuse detected. This session has been revoked.")

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
            await self._revoke_breached_family(user_id=token.user_id, family_id=token.family_id)
            raise TokenReuseError("Refresh token reuse detected. This session has been revoked.")

        return await self._issue_pair(
            user_id=token.user_id,
            family_id=token.family_id,
            parent_id=token.id,
            not_after=session_deadline,
        )

    async def _revoke_breached_family(self, *, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
        """Kill the login lineage whose refresh token was replayed — and only it.

        Scope is the FAMILY, not the user. This is what RFC 9700 (OAuth 2.0
        Security BCP) §4.14.2 prescribes for detected refresh-token reuse:
        revoke the token chain descended from the replayed token. It is also the
        only scope this code can justify, because a replay is genuinely
        ambiguous — the server cannot tell a thief from a client that legitimately
        holds a superseded token:

        * a laptop resumed from sleep, or a tab restored days later, replays the
          token it went to sleep holding;
        * a rotation that succeeded server-side but timed out client-side is
          retried by the SPA with the same (now consumed) cookie.

        Revoking every family on that evidence is what turned one such replay
        into a team-wide outage on 2026-07-27: a tab last used on the 24th woke
        up, replayed its long-dead token, and signed every other worker sharing
        the account out mid-task, across all 14 of that user's live families.
        Family scope still ends the ambiguous lineage — that device does have to
        log in again — while leaving every other device untouched.

        Revokes in a DEDICATED committed transaction: the calling request ends
        in a 401 (an exception), which rolls back the request-scoped session, so
        the revocation must persist independently or it would be silently undone.

        No Redis watermark is stamped: that key is per-user, so using it here
        would re-introduce exactly the account-wide blast radius this scopes
        away. The consequence — access tokens already issued on this family stay
        valid until they expire (15 minutes) — is the same one
        :meth:`logout` documents and accepts, and it is bounded.
        """
        logger.warning(
            "Refresh-token reuse detected for user %s; revoking family %s "
            "(other sessions of this user are left intact).",
            user_id,
            family_id,
        )
        async with AsyncSessionLocal() as breach_session:
            # Bound the wait for row locks. This revocation runs on a SECOND
            # connection while the caller's own transaction is still open and
            # may already hold locks on rows in this very family — so the two
            # can wait on each other. Unbounded, that wait ends only when
            # `idle_in_transaction_session_timeout` fires at five minutes, and
            # the request holds a pool slot for all of it.
            #
            # On 2026-07-28 six concurrent refreshes hit this path at once and
            # sat for 300 s each (measured: 300217-300231 ms, all returning
            # 401 in the same second). With the pool that starved, every other
            # user's request queued behind them — the site-wide freeze.
            #
            # Two seconds is far beyond a healthy uncontended UPDATE (~1 ms).
            # Past that, failing the revocation is strictly better than holding
            # the connection: the token was consumed and cannot rotate again, so
            # the replay is already dead — this only defers marking its siblings.
            await breach_session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
            try:
                await RefreshTokenRepository(breach_session).revoke_family(family_id)
                await breach_session.commit()
            except DBAPIError:
                await breach_session.rollback()
                logger.exception(
                    "Could not revoke family %s within the lock timeout; the replayed "
                    "token is already consumed, so the session cannot rotate regardless.",
                    family_id,
                )

    # ------------------------------------------------------------------ #
    # Logout
    # ------------------------------------------------------------------ #
    async def logout(self, *, refresh_secret: str | None) -> None:
        """Revoke the family associated with a presented refresh token.

        Silent no-op for a missing or unknown token so logout is idempotent and
        cannot be used as a user/token enumeration oracle.

        Family-scoped, and no Redis watermark: that key is per-user, so stamping
        it would sign every other device of the same user out too — "log out of
        this browser" is not "log out everywhere". The consequence is that the
        caller's own access token stays valid until it expires (15 minutes by
        default). That is acceptable because the SPA drops the token from memory
        on logout, and because narrowing it further would need a per-family
        watermark that buys nothing against a threat model where the attacker
        already holds the access token.

        :meth:`_revoke_breached_family` now uses the same scope and the same
        reasoning; see its docstring for why reuse detection stopped revoking
        account-wide.

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
