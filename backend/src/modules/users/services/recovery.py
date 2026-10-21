"""Email confirmation and password reset.

The register's warning is the design brief, and it is worth repeating because
everything below is shaped by it: *building this badly is worse than not having
it.* A reset flow is a full authentication path — it mints a session-changing
capability for whoever proves control of a mailbox — and it is the classic place
where the careful rules the login path follows get forgotten because the code
lives somewhere else.

So the three rules the login path already follows are re-applied here, and each
one is a place this could have leaked:

**It does not disclose whether an address is registered.** Every request
endpoint answers the same way for a known address, an unknown one and a disabled
account. That is the whole reason :meth:`request_password_reset` returns
``None`` instead of raising: an unknown address is not an error, it is a
non-event that must look exactly like the event.

**Codes are single-use, short-lived and hashed at rest**, with a capped number
of guesses — see :mod:`.verification`, which owns those properties.

**A completed reset ends every session.** Not the family, every session, on
every device: the case this exists for is "somebody else may have my password",
and leaving their sessions alive would hand the attacker exactly the thing the
reset was meant to take away. This is one of the two operations that may
legitimately stamp the per-user revocation watermark (the other is
``logout-all``), and it uses it for the same reason.

One thing this deliberately does *not* do
-----------------------------------------
It does not gate login on a confirmed address. Refusing an unconfirmed account
at ``/login`` would make the login response depend on account state, and the
uniform answer there is a control this codebase has paid for twice (P0.1, P1.5).
Confirmation is required where an address starts to *decide something* — taking
an activation code or an invitation, which is what puts a person inside a
company — and that check lives in ``deps.require_confirmed_email``.
"""

from __future__ import annotations

import asyncio

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.core.security import hash_password
from src.integrations.email import (
    EmailTransport,
    confirmation_message,
    password_reset_message,
)
from src.integrations.pwned import PasswordBreachCheck, PasswordBreachCheckLike
from src.modules.users.models import User, VerificationPurpose
from src.modules.users.repos import UserRepository
from src.modules.users.services.verification import VerificationService

logger = get_logger(__name__)


def _normalize_email(email: str) -> str:
    """Canonicalize an address the way registration and login do."""
    return email.strip().lower()


class AccountRecoveryService:
    """Confirms addresses and resets forgotten passwords.

    Args:
        users: Account repository.
        verification: Issues and redeems the codes.
        transport: Where a message goes. The logging transport in every
            environment without a relay, so the flow is exercisable end to end
            without one.
        breach_check: "Is this password already public?" — the same check
            registration runs. Injected so tests can drive it without HTTP.
    """

    def __init__(
        self,
        *,
        users: UserRepository,
        verification: VerificationService,
        transport: EmailTransport,
        breach_check: PasswordBreachCheckLike | None = None,
    ) -> None:
        """Wire the service to its collaborators."""
        self._users = users
        self._verification = verification
        self._transport = transport
        self._breach_check = breach_check or PasswordBreachCheck()

    # ------------------------------------------------------------------ #
    # Address confirmation
    # ------------------------------------------------------------------ #
    async def send_confirmation(
        self, *, user: User, pending_password_hash: str | None = None
    ) -> None:
        """Issue a confirmation code and mail it.

        Called at registration and by the resend endpoint. Silently does
        nothing for an address already confirmed — asking again is not an
        error, and re-sending would let anyone with a session spray mail at an
        address that has already proven itself.

        Args:
            user: The account whose address is being confirmed.
            pending_password_hash: The password this signup attempt asked for.
                Applied only when the code is redeemed — see
                :meth:`confirm_email`. Omitted by the resend endpoint, which
                inherits the candidate already on the live code.
        """
        if user.email_confirmed_at is not None:
            return
        code = await self._verification.issue(
            user_id=user.id,
            purpose=VerificationPurpose.EMAIL_CONFIRMATION,
            pending_password_hash=pending_password_hash,
        )
        await self._transport.send(
            confirmation_message(
                to=user.email,
                code=code,
                ttl_minutes=settings.verification_code_ttl_seconds // 60,
            )
        )

    async def confirm_email(self, *, email: str, code: str) -> User | None:
        """Redeem a confirmation code.

        Args:
            email: The address being confirmed.
            code: The code as typed.

        Returns:
            The confirmed account, or ``None`` for a wrong code, an expired one,
            or an address that was never registered — deliberately one answer
            for all three, so this endpoint is not the account-existence oracle
            ``/login`` refuses to be.

            The account rather than a bare ``True`` because the caller opens a
            session on it: redeeming the code proves the mailbox AND, since the
            password is bound to that same code, that this is the person who
            chose it. Making them type the password again immediately afterwards
            proves nothing further.
        """
        user = await self._users.get_by_email(_normalize_email(email))
        if user is None:
            return None
        redeemed = await self._verification.redeem(
            user_id=user.id, purpose=VerificationPurpose.EMAIL_CONFIRMATION, code=code
        )
        if redeemed is None:
            return None
        # THE PASSWORD IS SET HERE, not at registration, and that is the whole
        # defence. Whoever redeems the code is the one who read the mailbox, so
        # the password that survives is the one typed by that person in the same
        # attempt this code was issued for.
        #
        # Setting it at registration meant an attacker could sign up with
        # somebody else's address, and the victim — believing it their own
        # signup — would confirm it and hand over an account whose password the
        # attacker chose. Overwriting on each attempt instead only reverses who
        # wins; binding the two together is what removes the window.
        if redeemed.pending_password_hash is not None:
            await self._users.set_password(user, hashed_password=redeemed.pending_password_hash)
        await self._users.mark_email_confirmed(user)
        logger.info("Email confirmed for user %s.", user.id)
        return user

    # ------------------------------------------------------------------ #
    # Password reset
    # ------------------------------------------------------------------ #
    async def request_password_reset(self, *, email: str) -> None:
        """Mail a reset code, if there is anybody to mail it to.

        Returns nothing and raises nothing, whatever it finds. An unknown
        address, a disabled account and a live one all produce the same silence,
        because the caller's response must not differ — a reset form that
        answers "no such user" is an account enumeration endpoint with a
        friendly face.

        A disabled account is skipped rather than mailed: re-enabling is our
        decision, and a reset must not be a way around it.

        Args:
            email: The address as submitted.
        """
        user = await self._users.get_by_email(_normalize_email(email))
        if user is None or not user.is_active:
            logger.info("Password reset requested for an address with no live account.")
            return
        code = await self._verification.issue(
            user_id=user.id, purpose=VerificationPurpose.PASSWORD_RESET
        )
        await self._transport.send(
            password_reset_message(
                to=user.email,
                code=code,
                ttl_minutes=settings.verification_code_ttl_seconds // 60,
            )
        )

    async def reset_password(self, *, email: str, code: str, new_password: str) -> User | None:
        """Set a new password against a valid code.

        Does **not** end the account's sessions itself. That is the caller's
        job, and it is deliberate: revocation is a `revocation.py` concern with
        its own ordering rule (rows first, watermark second), and duplicating it
        here would be a second place that has to know it. The router does both
        in one transaction — see ``routers.reset_password``.

        Args:
            email: The account's address.
            code: The reset code as typed.
            new_password: The replacement password, already length-validated by
                the schema.

        Returns:
            The account on success, ``None`` for any failure — wrong code,
            expired code, unknown address, disabled account. One answer for all
            of them, for the same reason as everywhere else on this path.

        Raises:
            ValidationError: The new password appears in a public breach list.
                A distinct answer on purpose, and safe because it turns on the
                submitted password alone — see the comment at the check.
        """
        # FIRST, and before the account is even looked up. Registration
        # refused breached passwords and this path did not, which left the one
        # place it matters most unguarded: a person resetting a password is
        # often doing it BECAUSE the old one leaked, and this was where they
        # were free to pick another leaked one.
        #
        # The ordering is the security-relevant part. Run after the code check
        # it would answer differently for a real address than an unknown one —
        # both 422, but with different text — and that difference is an
        # account-existence oracle, which every other answer on this path is
        # built to deny. Run first, the outcome depends only on the password
        # the caller already knows, and it tells them nothing.
        if await self._breach_check.is_breached(new_password):
            raise ValidationError(
                "Этот пароль встречался в публичных утечках данных. Придумайте другой."
            )
        user = await self._users.get_by_email(_normalize_email(email))
        if user is None or not user.is_active:
            return None
        if not await self._verification.redeem(
            user_id=user.id, purpose=VerificationPurpose.PASSWORD_RESET, code=code
        ):
            return None
        # bcrypt is CPU-bound (~250 ms at the production work factor); off the
        # event loop, exactly as registration and login do it.
        hashed = await asyncio.to_thread(hash_password, new_password)
        await self._users.set_password(user, hashed_password=hashed)
        # Proving control of the mailbox is at least as good as proving control
        # of the old password, so a successful reset also settles the address.
        await self._users.mark_email_confirmed(user)
        logger.warning("Password reset completed for user %s.", user.id)
        return user


__all__ = ["AccountRecoveryService"]
