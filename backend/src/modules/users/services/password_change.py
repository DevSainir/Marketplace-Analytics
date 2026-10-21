"""Changing your own password while signed in.

The service had only the *forgotten*-password path: ask for a code, read the
mailbox, set a new password. A signed-in person who simply wants a different
password had to pretend to have lost the old one — and the SPA's "change
password" mailed a code with nowhere to type it, so the flow did not finish at
all.

**Why no mailed code here.** A code proves the mailbox, which is what the
forgotten-password path needs because it has nothing else. A signed-in caller
has already proved more than that, and the current password proves it again at
the moment of the change. OWASP's authentication guidance names the current
password as the control that matters here — without it, anyone holding a live
session can lock the owner out of their own account — and adds no second factor
for a change made from inside. Mailing a code as well would add a step that
proves nothing new and fails whenever mail is slow.

**What it does after the change.** Ends every OTHER session and keeps this one.
A password change is what somebody does when they think a credential got out, so
leaving the other sessions alive would defeat the point; signing the caller out
too would be a puzzle rather than a control.
"""

from __future__ import annotations

import asyncio
import uuid

from src.core.exceptions import AuthenticationError, ValidationError
from src.core.logging import get_logger
from src.core.security import hash_password, verify_password
from src.integrations.pwned import PasswordBreachCheck, PasswordBreachCheckLike
from src.modules.users.models import User
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.services.sessions import end_other_sessions

logger = get_logger(__name__)


class PasswordChangeService:
    """Set a new password for an already-authenticated account."""

    def __init__(
        self,
        *,
        users: UserRepository,
        tokens: RefreshTokenRepository,
        breach_check: PasswordBreachCheckLike | None = None,
    ) -> None:
        """Inject the repositories and the "is this password public?" check."""
        self._users = users
        self._tokens = tokens
        self._breach_check = breach_check or PasswordBreachCheck()

    async def change(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
        keep_family_id: uuid.UUID | None,
    ) -> int:
        """Replace one account's password, then end its other sessions.

        Args:
            user: The authenticated account, freshly loaded.
            current_password: What they say the password is now.
            new_password: What it should become.
            keep_family_id: The caller's own login lineage, spared from the
                sign-out. ``None`` when the access token predates the ``fam``
                claim, in which case every session ends including this one —
                the safe direction to be wrong in.

        Returns:
            How many other sessions were ended.

        Raises:
            AuthenticationError: The current password is wrong. Same shape as a
                failed login, and deliberately says nothing else.
            ValidationError: The new password is the old one, or is already
                public. The two messages differ because both are told to
                somebody who has just proved who they are — there is nothing
                left to withhold, and "pick a different one" is useless without
                saying why.
        """
        # bcrypt is CPU-bound (~100-300 ms); to_thread keeps the loop serving.
        if not await asyncio.to_thread(verify_password, current_password, user.hashed_password):
            logger.info("Password change refused for user %s: current password wrong.", user.id)
            raise AuthenticationError("Текущий пароль неверен.")

        if current_password == new_password:
            raise ValidationError("Новый пароль совпадает с текущим.")

        # Before the bcrypt cost, not after: no point spending 200 ms hashing a
        # password we are about to refuse. The check fails open, so a HIBP
        # outage costs a round trip and nothing else.
        if await self._breach_check.is_breached(new_password):
            raise ValidationError(
                "Этот пароль встречался в публичных утечках данных. Придумайте другой."
            )

        hashed = await asyncio.to_thread(hash_password, new_password)
        await self._users.set_password(user, hashed_password=hashed)

        ended = await end_other_sessions(
            tokens=self._tokens, user_id=user.id, keep_family_id=keep_family_id
        )
        logger.warning("User %s changed their password; %d other session(s) ended.", user.id, ended)
        return ended


__all__ = ["PasswordChangeService"]
