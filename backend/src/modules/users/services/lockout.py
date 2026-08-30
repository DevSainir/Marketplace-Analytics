"""Per-account cooling-off after repeated failed logins (register P1.5).

The IP throttle in :mod:`src.core.ratelimit` bounds how fast **one address** can
guess. It is the wrong shape for credential stuffing, which is the attack this
service actually faces: a list of address/password pairs leaked from somewhere
else, replayed a few tries per account from a rented pool of thousands of
addresses. Every request in that campaign is well inside the per-IP budget, so
the per-IP budget never fires. The quantity worth bounding is *attempts against
this account*, and nothing was counting it.

So this counts it, keyed on the account and nothing else.

Why a growing delay rather than a lock
--------------------------------------
A hard "locked until an administrator clears it" turns every guessed address
into a denial-of-service switch, and this service has no administrator sitting
by the phone to clear it. Exponential backoff keeps almost all of the defensive
value — 10 attempts costs an attacker the same 15 minutes it costs anyone —
while bounding what an attacker can do *to* a victim to a 15-minute nuisance
that expires by itself.

That nuisance is real and is the accepted cost: someone who knows your address
can keep your login unusable in 15-minute stretches. Two things make it
tolerable. It is capped, so it never becomes indefinite. And it only blocks
*new logins* — the refresh path is untouched, so sessions already open keep
working and a user who is signed in does not notice at all.

Why the key is a hash
---------------------
Redis persists to an AOF volume the backups include (see P1.11). A plaintext
key per attacked address turns that volume into a list of this service's
customers, which is a disclosure the feature does not need to make: the code
only ever compares keys, never reads them back, so a digest does the same job.

Availability
------------
Fails **open** — a Redis outage means no backoff, not a locked front door,
matching the policy in :mod:`src.core.redis` and :mod:`src.core.ratelimit`. The
outage is reported to :mod:`src.core.degradation`, which is what makes this
control's failure visible and, more importantly, lets one place notice that
this and the IP throttle went down in the same instant (P1.2).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Protocol

from redis.exceptions import RedisError

from src.core.degradation import CONTROL_LOGIN_BACKOFF, report_degraded, report_healthy
from src.core.redis import get_redis

#: Consecutive failures before any delay is imposed. Below this a person who
#: mistypes a password twice and then gets it right notices nothing.
DEFAULT_THRESHOLD = 5

#: The first penalty, in seconds. Doubles per further failure.
DEFAULT_BASE_SECONDS = 30

#: The longest a single penalty may last. The ceiling is what keeps a
#: deliberately-triggered backoff a nuisance rather than a takeover.
DEFAULT_MAX_SECONDS = 900

#: How long a run of failures is remembered when nothing further happens. Longer
#: than the maximum penalty, so an attacker cannot wait out the counter faster
#: than the penalty it produces.
DEFAULT_COUNTER_TTL_SECONDS = 3600


class LoginBackoffLike(Protocol):
    """The surface :class:`~src.modules.users.services.auth.AuthService` needs.

    Stated as a protocol so the test double is checked against the real
    contract structurally, rather than passed through a ``type: ignore``. A
    renamed method here breaks both implementations at once, which is the
    property a hand-written fake is supposed to give.
    """

    async def penalty_remaining(self, *, email: str) -> int:
        """Return seconds this account must wait, ``0`` when free."""
        ...

    async def record_failure(self, *, email: str) -> None:
        """Count one failed attempt against this account."""
        ...

    async def clear(self, *, email: str) -> None:
        """Forget this account's failures."""
        ...


def _digest(email: str) -> str:
    """Return the stable, non-reversible key fragment for an account."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


class LoginBackoff:
    """Counts consecutive login failures per account and prices the next try.

    Injected into :class:`~src.modules.users.services.auth.AuthService` rather
    than reached for directly, so a unit test drives a fake instead of a socket.

    Args:
        threshold: Consecutive failures tolerated before any penalty.
        base_seconds: Penalty for the first failure past the threshold.
        max_seconds: Ceiling on a single penalty.
        counter_ttl_seconds: How long the failure count survives inactivity.
    """

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        base_seconds: int = DEFAULT_BASE_SECONDS,
        max_seconds: int = DEFAULT_MAX_SECONDS,
        counter_ttl_seconds: int = DEFAULT_COUNTER_TTL_SECONDS,
    ) -> None:
        """Store the backoff schedule."""
        self._threshold = threshold
        self._base = base_seconds
        self._max = max_seconds
        self._counter_ttl = counter_ttl_seconds

    async def penalty_remaining(self, *, email: str) -> int:
        """Return how many seconds this account must wait, ``0`` when free.

        Args:
            email: The normalized account email being attempted.

        Returns:
            Seconds remaining on the current penalty, or ``0`` — including when
            Redis is unreachable, matching the fail-open policy.
        """
        try:
            raw = await get_redis().get(self._block_key(email))
        except RedisError as exc:
            self._degraded(exc, "penalty lookup skipped")
            return 0
        report_healthy(CONTROL_LOGIN_BACKOFF)
        if raw is None:
            return 0
        try:
            lifts_at = float(raw)
        except (TypeError, ValueError):
            return 0
        return max(0, int(lifts_at - self._now()))

    async def record_failure(self, *, email: str) -> None:
        """Count one failed attempt and impose a penalty once past the threshold.

        Args:
            email: The normalized account email that was attempted.
        """
        try:
            redis = get_redis()
            failures = await redis.incr(self._counter_key(email))
            await redis.expire(self._counter_key(email), self._counter_ttl)
            penalty = self._penalty_for(failures)
            if penalty:
                await redis.set(
                    self._block_key(email),
                    str(self._now() + penalty),
                    ex=penalty,
                )
        except RedisError as exc:
            self._degraded(exc, "failed attempt not counted")
            return
        report_healthy(CONTROL_LOGIN_BACKOFF)

    async def clear(self, *, email: str) -> None:
        """Forget this account's failures after a successful authentication.

        Args:
            email: The normalized account email that just authenticated.
        """
        try:
            redis = get_redis()
            await redis.delete(self._counter_key(email))
            await redis.delete(self._block_key(email))
        except RedisError as exc:
            self._degraded(exc, "counter not cleared after a successful login")
            return
        report_healthy(CONTROL_LOGIN_BACKOFF)

    def _penalty_for(self, failures: int) -> int:
        """Return the penalty in seconds owed after ``failures`` consecutive misses."""
        overshoot = failures - self._threshold
        if overshoot < 0:
            return 0
        # Shift rather than ``2 ** overshoot``: int ** int is Any to a type
        # checker (a negative exponent yields a float), and a doubling is
        # exactly what a left shift says.
        return min(self._base * (1 << overshoot), self._max)

    def _counter_key(self, email: str) -> str:
        """Key holding the consecutive-failure count."""
        return f"auth:login-fails:{_digest(email)}"

    def _block_key(self, email: str) -> str:
        """Key holding the instant the current penalty lifts."""
        return f"auth:login-block:{_digest(email)}"

    def _now(self) -> float:
        """Current wall-clock time as a UNIX timestamp."""
        return datetime.now(UTC).timestamp()

    def _degraded(self, exc: RedisError, what: str) -> None:
        """Report this control as failing open. Never carries the account."""
        report_degraded(CONTROL_LOGIN_BACKOFF, detail=f"{what}: {type(exc).__name__}: {exc}")


__all__ = ["LoginBackoff", "LoginBackoffLike"]
