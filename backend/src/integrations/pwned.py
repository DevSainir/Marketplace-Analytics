"""Have I Been Pwned's range API — "has this password already leaked?" (P1.5).

Length is a bad proxy for password strength and it is the only rule this service
had. `Password1!` clears an 8-character minimum and appears in breach corpora
millions of times; it is the first thing a stuffing list tries. The cheapest
real improvement is to refuse passwords that are already public, which is what
this asks.

The k-anonymity protocol, and why it is safe to use
---------------------------------------------------
The password never leaves this process, and neither does its full hash. We take
SHA-1 of the candidate, send the **first five hex characters** and receive every
known suffix sharing that prefix — some hundreds of hashes — then look for ours
locally. The service learns that somebody, somewhere, checked a password whose
hash begins with those five characters, which is roughly one bucket in a million
and matched by a large slice of the corpus. It never learns which password, and
never learns anything at all about our users.

Two details make that hold in practice rather than only on paper:

* **SHA-1 here is not a security choice**, it is the protocol's wire format. The
  password is stored with bcrypt, as it always was; this hash exists for the
  duration of one HTTP call and is never persisted.
* **`Add-Padding: true`** asks HIBP to pad every response to a uniform size.
  Without it, an observer who can see the encrypted response *length* can narrow
  down which prefix was requested, which gives back some of what k-anonymity was
  protecting.

Failure policy: **open**, and that is a considered choice rather than laziness.
This is a quality gate on a password the user is choosing, not a control
standing between an attacker and an account. If HIBP is unreachable, refusing
the registration would convert somebody else's outage into ours, and the
resulting account is no worse than every account created before this existed. A
warning is logged; nothing is reported to the P1.2 degradation ledger, which is
deliberately reserved for controls that protect live sessions — diluting that
signal with a third party's availability is how a combined-degradation alert
stops meaning anything.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import httpx

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

#: The range endpoint. Documented as free, unauthenticated and rate-limited by
#: prefix rather than by caller.
RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"

#: HIBP asks that callers identify themselves.
USER_AGENT = "marketplace-analytics-password-check"


class PasswordBreachCheckLike(Protocol):
    """The surface the auth service needs, stated so a fake can satisfy it."""

    async def is_breached(self, password: str) -> bool:
        """Report whether this password appears in a known breach corpus."""
        ...


class PasswordBreachCheck:
    """Queries HIBP's range API for one password, k-anonymously.

    Args:
        timeout_seconds: Whole-request budget. Short on purpose — this sits in
            the registration path, and a slow third party must not become a slow
            signup form.
    """

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        """Store the request budget, defaulting to the configured one."""
        self._timeout = timeout_seconds or settings.password_breach_check_timeout_seconds

    async def is_breached(self, password: str) -> bool:
        """Report whether this password is already public.

        Args:
            password: The plaintext candidate. Never logged, never sent.

        Returns:
            ``True`` only when the suffix is found in HIBP's answer. Anything
            else — disabled by configuration, a timeout, a non-200, a malformed
            body — is ``False``, so the check can never block a registration by
            failing.
        """
        if not settings.password_breach_check_enabled:
            return False

        prefix, suffix = _split_hash(password)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.get(
                    RANGE_URL.format(prefix=prefix),
                    headers={"Add-Padding": "true", "User-Agent": USER_AGENT},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "Password breach check unavailable (%s: %s); allowing the password.",
                type(exc).__name__,
                exc,
            )
            return False
        return _suffix_is_listed(response.text, suffix)


def _split_hash(password: str) -> tuple[str, str]:
    """Return the 5-character prefix and 35-character suffix of the SHA-1.

    Args:
        password: The plaintext candidate.

    Returns:
        ``(prefix, suffix)``, uppercase hex, as the range API expects.
    """
    # usedforsecurity=False says what the comment above says, to the library:
    # this digest is a wire format, not a password hash. bcrypt does that job.
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    return digest[:5], digest[5:]


def _suffix_is_listed(body: str, suffix: str) -> bool:
    """Search a range response for our suffix.

    The body is ``SUFFIX:COUNT`` per line. Padding rows carry a count of ``0``
    and are ignored — treating one as a hit would reject perfectly good
    passwords at random.

    Args:
        body: The range endpoint's response text.
        suffix: The 35-character suffix being looked for.

    Returns:
        Whether the suffix appears with a non-zero count.
    """
    for line in body.splitlines():
        candidate, _, count = line.strip().partition(":")
        if candidate.upper() != suffix:
            continue
        try:
            return int(count) > 0
        except ValueError:
            return False
    return False


__all__ = ["PasswordBreachCheck", "PasswordBreachCheckLike"]
