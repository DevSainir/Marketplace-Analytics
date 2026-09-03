"""Creating an account, and what one signup attempt produces.

Split out of :mod:`.auth` for the same reason the rest of this package was:
that module owns *sessions* — issuing, rotating and ending them — and creating
an account is a different job that happens to be reachable from the same
router. It also carries the one rule in this module worth reading before
changing anything here.

**The password does not land on the account at registration.** It travels on
the confirmation code and is applied when that code is redeemed
(:meth:`AccountRecoveryService.confirm_email`), so that proving control of the
mailbox and choosing the password are ONE act by ONE person.

Doing it the obvious way is an account takeover. Write the password at
registration and never replace it, and an attacker signs up with somebody
else's address first; the victim receives what looks like their own
confirmation mail, enters the code, and the account goes live with the
attacker's password. Replace it on every attempt instead and the same thing
happens with the order reversed — the attacker signs up second, and the
victim's confirmation applies the attacker's password. Only binding the two
together closes both.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, ValidationError
from src.core.logging import get_logger
from src.core.security import hash_password
from src.integrations.pwned import PasswordBreachCheck, PasswordBreachCheckLike
from src.modules.users.repos import UserRepository
from src.modules.users.schemas import UserRead

logger = get_logger(__name__)


@dataclass(frozen=True)
class RegistrationOutcome:
    """What one signup attempt produced.

    Attributes:
        account: The account the attempt belongs to — freshly created, or the
            unconfirmed one it resumed.
        password_hash: The digest of the password this attempt asked for. The
            caller binds it to the confirmation code instead of to the account,
            which is what makes proving the mailbox and choosing the password
            one act rather than two.
        created: Whether a row was inserted. Only useful for logging and tests;
            the response is deliberately identical either way.
    """

    account: UserRead
    password_hash: str
    created: bool


def _normalize_email(email: str) -> str:
    """Canonicalize an email for storage and lookup.

    Lowercasing the whole address means ``User@X.com`` and ``user@x.com`` are
    one account: without it, case-variant duplicates register freely and users
    who typed mixed case at signup fail later logins. (RFC 5321 technically
    allows a case-sensitive local part; in practice no mainstream provider is,
    and login ergonomics win.)

    Duplicated in :mod:`.auth` rather than shared: registration and login must
    canonicalize identically, and a shared helper is a single place where a
    well-meaning change breaks both at once — silently, since the failure is a
    lookup that misses rather than an error.
    """
    return email.strip().lower()


class RegistrationService:
    """Creates accounts. Issues nothing — sessions are :mod:`.auth`'s job."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        breach_check: PasswordBreachCheckLike | None = None,
    ) -> None:
        """Inject the account repository and the breach check.

        Args:
            user_repo: Repository for :class:`User` persistence.
            breach_check: "Is this password already public?" check. Injected so
                a test drives a fake instead of a socket; defaults to the Have I
                Been Pwned range query.
        """
        self._users = user_repo
        self._breach_check = breach_check or PasswordBreachCheck()

    async def register(self, *, email: str, password: str) -> RegistrationOutcome:
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
            The account, the digest of the password this attempt asked for, and
            whether the row was created. The digest travels to the confirmation
            code rather than to the account — see
            :meth:`AccountRecoveryService.confirm_email` for why.

        Raises:
            ConflictError: If the email is already registered AND confirmed. An
                unconfirmed one is resumed rather than refused.
            ValidationError: If the password is already public — see
                :mod:`src.integrations.pwned` for what that check does and does
                not disclose.
        """
        email = _normalize_email(email)
        existing = await self._users.get_by_email(email)
        if existing is not None:
            # An unconfirmed row is an unfinished signup, almost always by the
            # same person — so this is not a clash to refuse but a flow to
            # resume. The password is deliberately NOT overwritten: whoever
            # holds the mailbox finishes with the code, and anyone else has
            # changed nothing. A confirmed account is a real conflict.
            if existing.email_confirmed_at is None:
                # An unconfirmed row is an unfinished signup. Repeating it is
                # allowed, and the new password is NOT written to the account
                # here — it is carried on the code and applied when that code is
                # redeemed, so the password that survives belongs to whoever
                # read the mailbox. Writing it now would let an attacker who
                # signs up after the victim own the password the victim then
                # confirms; refusing outright let an attacker who signs up
                # BEFORE them do the same. Neither is a window this leaves open.
                return RegistrationOutcome(
                    account=UserRead.model_validate(existing),
                    password_hash=await asyncio.to_thread(hash_password, password),
                    created=False,
                )
            raise ConflictError(
                "Аккаунт с такой почтой уже существует — войдите или восстановите пароль."
            )
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
            raise ConflictError(
                "Аккаунт с такой почтой уже существует — войдите или восстановите пароль."
            ) from exc
        return RegistrationOutcome(
            account=UserRead.model_validate(user),
            password_hash=hashed,
            created=True,
        )
