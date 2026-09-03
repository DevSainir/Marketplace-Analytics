"""Issuing and redeeming the codes that prove control of an email address.

One mechanism, two purposes — confirming an address and resetting a password —
kept apart by a column rather than by two tables, because everything that makes
them safe is identical and duplicating it would mean maintaining it twice.

What makes a six-digit code safe
--------------------------------
Six digits is a million possibilities. That is a small number, and it is only
acceptable because guessing is bounded on four axes at once. Remove any one and
the length becomes a real problem, so all four are stated here rather than left
to be inferred:

* **The row expires.** Fifteen minutes by default.
* **Attempts are capped.** A wrong guess increments a counter; at the cap the
  row is consumed — dead, not merely disbelieved — so the attacker must request
  a new code, which invalidates the one they were working on.
* **Issuing is single-flight per purpose.** A new code supersedes the previous
  one for that account and purpose, so an attacker cannot accumulate a pool of
  live codes to guess against by spamming the request endpoint.
* **The endpoints sit behind the per-IP throttle**, and the request endpoints
  behind the per-account backoff added in P1.5.

Stored hashed, like everything else here
----------------------------------------
The row holds SHA-256 of the code, never the code. A database dump, a backup or
a stray ``SELECT *`` yields nothing redeemable. This is the same rule as
``activation_codes.code_hash`` and ``refresh_tokens.token_hash``; the only
difference is that this credential is measured in minutes.

SHA-256 rather than bcrypt is deliberate and is the one place that reasoning
differs from passwords: a six-digit code has no entropy for a slow hash to
protect — an attacker who has the digest can enumerate a million candidates
whatever the cost function — so the work factor would buy nothing and cost
~250 ms on a path a person waits on. What protects the code is the attempt cap
and the TTL, both of which live in this table.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from src.core.config import settings
from src.core.logging import get_logger
from src.core.security import hash_opaque_secret
from src.modules.users.models import VerificationCode, VerificationPurpose
from src.modules.users.repos import VerificationCodeRepository

logger = get_logger(__name__)


def generate_code(length: int | None = None) -> str:
    """Return a fresh numeric code.

    Uses :mod:`secrets`, not :mod:`random`: this is a credential, and a
    predictable one is not a credential at all.

    Args:
        length: Digits to produce; the configured length when omitted.

    Returns:
        A zero-padded decimal string — ``"004271"`` is a valid code, and
        dropping the leading zero would quietly shrink the keyspace.
    """
    digits = length or settings.verification_code_length
    return f"{secrets.randbelow(10**digits):0{digits}d}"


class VerificationService:
    """Issues and redeems verification codes for one request."""

    def __init__(self, *, codes: VerificationCodeRepository) -> None:
        """Inject the code repository."""
        self._codes = codes

    async def issue(
        self,
        *,
        user_id: uuid.UUID,
        purpose: VerificationPurpose,
        pending_password_hash: str | None = None,
    ) -> str:
        """Mint a code, replacing any live one for this account and purpose.

        Replacing rather than adding is a security property, not tidiness: two
        live codes double an attacker's chances per guess, and a hundred live
        codes — which an unchecked request endpoint would produce — turn a
        million-candidate space into a ten-thousand-candidate one.

        Args:
            user_id: The account the code is issued to.
            purpose: What it will prove.
            pending_password_hash: The password this attempt asked for, applied
                on redemption. When omitted, the candidate on the code being
                REPLACED is carried forward — a plain "send it again" must not
                silently drop the password the person typed at signup, which
                would leave whatever the account was created with standing.

        Returns:
            The plaintext code. The caller mails it; nothing else may keep it.
        """
        if pending_password_hash is None:
            live = await self._codes.get_live(user_id=user_id, purpose=str(purpose))
            pending_password_hash = live.pending_password_hash if live else None
        await self._codes.consume_live_codes(user_id=user_id, purpose=str(purpose))
        code = generate_code()
        await self._codes.create(
            user_id=user_id,
            purpose=str(purpose),
            code_hash=hash_opaque_secret(code),
            pending_password_hash=pending_password_hash,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.verification_code_ttl_seconds),
        )
        return code

    async def redeem(
        self, *, user_id: uuid.UUID, purpose: VerificationPurpose, code: str
    ) -> VerificationCode | None:
        """Check a presented code and consume it on success.

        A wrong guess costs an attempt; the row dies at the cap. An expired or
        already-consumed row is simply not found, so a replay and a wrong guess
        are indistinguishable to the caller — which is the answer both should
        get.

        Args:
            user_id: The account presenting the code.
            purpose: What the code must have been issued for. A confirmation
                code presented to the reset flow does not match, because the
                lookup is scoped by this.
            code: The plaintext code as typed.

        Returns:
            The consumed row on success, ``None`` on any failure. The row rather
            than a bare ``True`` because the caller needs what it carried — the
            candidate password bound to this attempt. Falsy on failure, so the
            call still reads as a condition.
        """
        row = await self._codes.get_live(user_id=user_id, purpose=str(purpose))
        if row is None:
            return None

        if not secrets.compare_digest(row.code_hash, hash_opaque_secret(code)):
            attempts = await self._codes.record_attempt(row)
            if attempts >= settings.verification_code_max_attempts:
                # Consumed, not merely counted: leaving the row alive at the cap
                # would let an attacker keep the same target while a legitimate
                # user's new request replaced nothing.
                await self._codes.consume(row)
                logger.warning(
                    "Verification code for user %s (%s) exhausted its attempts and was killed.",
                    user_id,
                    purpose,
                )
            return None

        await self._codes.consume(row)
        return row


def is_live(row: VerificationCode, *, now: datetime | None = None) -> bool:
    """Whether a code row can still be redeemed.

    Args:
        row: The stored code.
        now: Current time, injectable for tests.

    Returns:
        ``True`` when the row is neither consumed nor expired.
    """
    moment = now or datetime.now(UTC)
    return row.consumed_at is None and row.expires_at > moment


__all__ = ["VerificationService", "generate_code", "is_live"]
