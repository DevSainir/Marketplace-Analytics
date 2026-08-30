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
* **Per-account backoff:** consecutive login failures make the next attempt on
  that account wait, independently of the per-IP throttle — the budget a
  credential-stuffing campaign spread across thousands of addresses never
  touches (:mod:`.lockout`).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.core.config import settings
from src.core.exceptions import (
    AuthenticationError,
    ConflictError,
    TokenReuseError,
    ValidationError,
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
from src.integrations.pwned import PasswordBreachCheck, PasswordBreachCheckLike
from src.modules.users.models import RefreshToken
from src.modules.users.refresh_grace import (
    await_rotation,
    recall_rotation,
    remember_rotation,
)
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.schemas import IssuedTokens, UserRead
from src.modules.users.services.breach import revoke_breached_family
from src.modules.users.services.lockout import LoginBackoff, LoginBackoffLike

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
        backoff: LoginBackoffLike | None = None,
        breach_check: PasswordBreachCheckLike | None = None,
    ) -> None:
        """Inject the collaborating repositories.

        Args:
            user_repo: Repository for :class:`User` persistence.
            token_repo: Repository for :class:`RefreshToken` persistence.
            backoff: Per-account login backoff. Injected so a test can drive a
                fake instead of a socket; defaults to the Redis-backed one.
            breach_check: "Is this password already public?" check. Injected for
                the same reason; defaults to the Have I Been Pwned range query.
        """
        self._users = user_repo
        self._tokens = token_repo
        self._backoff = backoff or LoginBackoff()
        self._breach_check = breach_check or PasswordBreachCheck()

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    async def register(self, *, email: str, password: str) -> UserRead:
        """Register a new user account.

        **Registration is open, and there is no longer a code that closes it.**
        A new account is deliberately powerless: it belongs to no organisation,
        and every data route in the platform sits behind ``require_member``, so
        a bare signup can reach exactly two things — the activation screen and
        its own pending invitations. Access is granted afterwards, by redeeming
        an activation code (becoming an owner) or accepting an invitation
        (becoming a manager). That is what makes an open form safe here; it is
        not safe on its own.

        The shared gate code that used to sit in front of this was removed
        deliberately. It was one secret shared by everyone who had it, guessable
        against this endpoint, and it made "is signup open?" a question with two
        answers — the code's and the organisation model's. Closing signup again
        is now a code change rather than a config change; that is the accepted
        cost.

        Args:
            email: Desired unique login email (normalized to lowercase).
            password: Plaintext password (hashed before persistence).

        Returns:
            The newly created account as a :class:`UserRead` DTO (the router
            returns it verbatim — no presentation-layer mapping needed).

        Raises:
            ConflictError: If the email is already registered.
            ValidationError: If the password is already public — see
                :mod:`src.integrations.pwned` for what that check does and does
                not disclose.
        """
        email = _normalize_email(email)
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise ConflictError("A user with this email already exists.")
        # Before the bcrypt cost, not after: there is no point spending 200 ms
        # hashing a password we are about to refuse. The check fails open, so a
        # HIBP outage costs a round trip and nothing else.
        if await self._breach_check.is_breached(password):
            raise ValidationError(
                "Этот пароль встречался в публичных утечках данных. Придумайте другой."
            )
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

        The lookup path is deliberately constant-time: whatever the outcome,
        exactly one bcrypt verification runs — against :data:`DUMMY_HASH` when
        the email is unknown — so an attacker cannot distinguish "no such
        user", "wrong password", "disabled account" or "currently backed off"
        by measuring latency any more than by reading the message.

        Consecutive failures on one account impose a growing delay before the
        next attempt is considered at all; a success clears it. See
        :mod:`src.modules.users.services.lockout` for the schedule and for why
        the denial-of-service this trades against is bounded and accepted.

        Args:
            email: Submitted login email.
            password: Submitted plaintext password.

        Returns:
            A fresh :class:`IssuedTokens` bundle.

        Raises:
            AuthenticationError: On unknown user, wrong password, inactive
                account, or an account still inside its backoff (deliberately
                the same message for all four, so the response is neither an
                account-existence oracle nor a report on the attack's progress).
        """
        email = _normalize_email(email)
        penalty = await self._backoff.penalty_remaining(email=email)
        user = await self._users.get_by_email(email)

        # bcrypt is CPU-bound (~100-300 ms); to_thread keeps the event loop
        # serving other requests instead of stalling the whole process.
        #
        # The verify below is unconditional, and that is the point. A backed-off
        # account that returned early would answer in a millisecond where every
        # other rejection takes a bcrypt cycle, and that gap is an oracle for
        # *two* facts at once: that the account is under attack, and — since
        # only a real account accumulates failures — that it exists at all. The
        # constant-time property this method already had has to survive the new
        # branch, not just precede it.
        hashed = user.hashed_password if user is not None else DUMMY_HASH
        password_matches = await asyncio.to_thread(verify_password, password, hashed)

        if penalty:
            logger.info(
                "Login refused during a %ds backoff (consecutive failures on this account).",
                penalty,
            )
            raise AuthenticationError("Invalid email or password.")

        if user is None or not password_matches:
            await self._backoff.record_failure(email=email)
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            # Counted like any other failure: not doing so would make a disabled
            # account the one address that never backs off, which is a
            # difference an attacker can measure.
            await self._backoff.record_failure(email=email)
            logger.info("Login attempt for disabled account %s.", user.id)
            raise AuthenticationError("Invalid email or password.")

        await self._backoff.clear(email=email)

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

        # --- Consumed token: a racing tab, or a genuine replay. ---
        # These are indistinguishable from the token alone, so the difference is
        # made by WHEN: a presentation within the grace window of the rotation
        # that consumed it is served that rotation's child (see
        # :mod:`src.modules.users.refresh_grace`), and everything later is a
        # breach. Serving the same child rather than issuing a sibling is what
        # keeps one live leaf per family, so detection still works afterwards.
        if token.is_used:
            replayed = await self._serve_from_grace(token)
            if replayed is not None:
                return replayed
            await revoke_breached_family(user_id=token.user_id, family_id=token.family_id)
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
            # Lost the race rather than replayed: another request consumed this
            # token between our read and this UPDATE. That is the same two-tab
            # collision as the fast path, arriving a few milliseconds tighter, so
            # it gets the same answer — after waiting for the winner to publish
            # the child it is about to issue.
            replayed = await self._serve_from_grace(token, wait=True)
            if replayed is not None:
                return replayed
            await revoke_breached_family(user_id=token.user_id, family_id=token.family_id)
            raise TokenReuseError("Refresh token reuse detected. This session has been revoked.")

        issued = await self._issue_pair(
            user_id=token.user_id,
            family_id=token.family_id,
            parent_id=token.id,
            not_after=session_deadline,
        )
        await remember_rotation(parent_id=token.id, refresh_secret=issued.refresh_secret)
        return issued

    async def _serve_from_grace(
        self, token: RefreshToken, *, wait: bool = False
    ) -> IssuedTokens | None:
        """Re-serve the child of a just-consumed token to a racing presenter.

        Args:
            token: The consumed token that was presented again.
            wait: Whether to wait briefly for a rotation still in flight. Set on
                the lost-race path, where the winner may not have recorded its
                child yet; unset on the replay path, where any rotation of this
                token finished long ago.

        Returns:
            A bundle carrying the child that the rotation already issued, or
            ``None`` when there is no live grace entry — which puts the caller
            back on the breach path, exactly as before this existed.
        """
        secret = (
            await await_rotation(parent_id=token.id)
            if wait
            else await recall_rotation(parent_id=token.id)
        )
        if secret is None:
            return None
        child = await self._tokens.get_by_hash(hash_refresh_secret(secret))
        # The child must still be the family's live leaf. If it has itself been
        # rotated, revoked or expired inside the grace window, the entry is
        # stale and re-serving it would hand back a token that cannot be used —
        # so fall through and let breach detection decide.
        if (
            child is None
            or child.is_used
            or child.is_revoked
            or child.expires_at <= datetime.now(UTC)
        ):
            return None
        logger.info(
            "Concurrent refresh of token %s served the rotation already issued "
            "(family %s left intact).",
            token.id,
            token.family_id,
        )
        access_token, access_expires_at = create_access_token(user_id=child.user_id, jti=child.id)
        return IssuedTokens(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_secret=secret,
            refresh_expires_at=child.expires_at,
        )

    # ------------------------------------------------------------------ #
    # Logout
    # ------------------------------------------------------------------ #
    async def revoke_all_sessions(self, *, user_id: uuid.UUID) -> int:
        """End every session of one account, immediately and on every device.

        The account-wide counterpart of :meth:`logout`, and the one operation
        that legitimately stamps the Redis watermark. ``logout`` and
        :func:`revoke_breached_family` both refuse to, because that key is
        per-user and they are per-family — "log out of this browser" and "end
        the lineage that leaked" are not "end everything". This is, so it does.

        Both halves are needed and neither is sufficient. Revoking the refresh
        rows stops new pairs being minted but leaves outstanding **access**
        tokens valid for up to their 15-minute TTL, which is exactly the window
        an incident response cannot afford. The watermark closes that window by
        rejecting any access token issued before this moment
        (``get_current_user_id`` checks it on every request). It is also why the
        machinery existed but was unreachable: ``mark_user_sessions_revoked``
        was called from tests only, so the watermark could never be set and
        incident response had no lever at all (register P1.1).

        Order matters. The rows are revoked first and the watermark stamped
        after, so a rotation racing this call finds no live row to rotate. The
        reverse order would leave a gap in which a fresh pair is minted with an
        ``iat`` past the watermark and survives.

        Args:
            user_id: The account whose sessions all end.

        Returns:
            How many refresh rows were revoked — 0 is a normal answer for an
            account with no live session, not a failure.
        """
        revoked = await self._tokens.revoke_all_for_user(user_id)
        await mark_user_sessions_revoked(user_id)
        logger.warning("All sessions revoked for user %s (%d refresh rows).", user_id, revoked)
        return revoked

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
