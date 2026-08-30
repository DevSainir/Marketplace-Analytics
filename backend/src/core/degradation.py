"""Noticing when a security control has quietly stopped protecting anything.

Several controls in this service **fail open** on a Redis outage, each for a
defensible reason: the auth rate limiter is an abuse dampener, not a correctness
guarantee, and refusing every authenticated request because a cache is down is a
worse failure than widening the revocation window back to the access-token TTL.
Those decisions stand. What did not stand is the *silence around them*.

Two things were missing, and this module supplies both.

**A degradation is an event, not a line per request.** Each control already
logged its own failure — from inside the request path, so one Redis outage
produced one ``logger.exception`` per request, thousands of identical
tracebacks that no alert can usefully fire on and no human reads. A flood is
indistinguishable from silence. Here a control reports its state on every call
and the *ledger* decides what is worth saying: the transition into degradation,
a heartbeat no more often than :data:`_COOLDOWN_SECONDS`, and the recovery.

**Nobody was watching the combination.** The register's actual finding (P1.2)
is not that either control fails open — it is that the *same* outage removes
brute-force protection and session revocation together, so an attacker who
notices can guess passwords without limit against accounts nobody can log out.
Neither control can see that; only something above both can. When two or more
report degraded inside one window, this module says so as its own, louder event.

Deliberately in-process and side-effect free
--------------------------------------------
No Redis (Redis is the thing that is down), no HTTP, no disk, nothing to await.
The reporting calls sit in the request path, so they must not be able to fail,
block, or become the next outage. What comes out is a log record at CRITICAL
carrying a stable, greppable event token — :data:`EVENT_DEGRADED`,
:data:`EVENT_COMBINED`, :data:`EVENT_RECOVERED` — which is what an alert rule
binds to. Shipping those records somewhere that pages a human is P2.1/P2.2's
job; this module's contract is that the record exists, exactly once, and names
the risk in words.

State is per-process, so *n* API replicas raise up to *n* alerts for one
outage. That is the right trade: deduplicating across replicas would need a
shared store, and the shared store is Redis.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.core.logging import get_logger

logger = get_logger(__name__)

#: Stable tokens an alert rule matches on. They are values, not f-strings, so
#: that grepping the codebase for an alert leads back to the control that
#: raises it.
EVENT_DEGRADED = "SECURITY_CONTROL_DEGRADED"
EVENT_COMBINED = "SECURITY_CONTROLS_DEGRADED_TOGETHER"
EVENT_RECOVERED = "SECURITY_CONTROL_RECOVERED"

#: The auth rate limiter (`src.core.ratelimit`). Failing open means unlimited
#: password guessing against `/login`.
CONTROL_AUTH_RATE_LIMIT = "auth-rate-limit"

#: The per-user session-revocation watermark (`src.core.redis`). Failing open
#: means "log out everywhere" does not reach access tokens already issued, and
#: a revocation performed *during* the outage is silently lost.
CONTROL_SESSION_REVOCATION = "session-revocation"

#: The per-account login backoff (`src.modules.users.services.lockout`). Failing
#: open means credential stuffing is bounded only by the per-IP throttle, which
#: is the budget a distributed campaign never touches.
CONTROL_LOGIN_BACKOFF = "login-backoff"

#: How often one still-degraded control repeats itself. Long enough that an
#: hour-long outage produces a readable handful of records rather than a flood;
#: short enough that the heartbeat proves the outage is ongoing.
_COOLDOWN_SECONDS = 60.0

#: How long a report keeps counting toward "degraded right now" for the purpose
#: of the combined event. A control that has not reported since is either
#: healthy again or not being exercised; either way it is not evidence.
_CORRELATION_WINDOW_SECONDS = 120.0


class DegradationLedger:
    """Tracks which security controls are failing open, and says so once.

    One instance per process is enough — see :data:`_ledger`. The class exists
    so tests can drive a fresh ledger with an injected clock instead of waiting
    out a real cooldown.

    Every method is synchronous and does no I/O, which is what makes it safe to
    call from the request path of a service that is already having a bad day.

    Args:
        clock: Monotonic time source, in seconds. Injected for tests.
        cooldown_seconds: Minimum gap between repeat reports of one control.
        correlation_window_seconds: How recently two controls must both have
            reported for the combination to count as simultaneous.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        cooldown_seconds: float = _COOLDOWN_SECONDS,
        correlation_window_seconds: float = _CORRELATION_WINDOW_SECONDS,
    ) -> None:
        """Start with every control presumed healthy."""
        self._clock = clock
        self._cooldown = cooldown_seconds
        self._window = correlation_window_seconds
        #: control -> when it most recently reported itself degraded.
        self._last_seen: dict[str, float] = {}
        #: control -> when we most recently said so out loud.
        self._last_logged: dict[str, float] = {}
        #: when the combined event was most recently raised.
        self._combined_logged: float | None = None

    def report_degraded(self, control: str, *, detail: str) -> None:
        """Record that ``control`` just failed open, and log if it is news.

        Args:
            control: One of the ``CONTROL_*`` constants in this module.
            detail: Short human-readable cause, e.g. the exception class. Must
                never carry a secret, a token or a password — this string
                reaches the log verbatim.
        """
        now = self._clock()
        is_new = control not in self._last_seen
        self._last_seen[control] = now

        if is_new or self._due(self._last_logged.get(control), now):
            self._last_logged[control] = now
            logger.critical(
                "%s control=%s detail=%s — this control is currently protecting nothing.",
                EVENT_DEGRADED,
                control,
                detail,
            )

        self._maybe_report_combination(now)

    def report_healthy(self, control: str) -> None:
        """Record that ``control`` is working again, and log the recovery once.

        Cheap enough to call on every success: for a healthy control this is one
        dict lookup and a return.

        Args:
            control: One of the ``CONTROL_*`` constants in this module.
        """
        if control not in self._last_seen:
            return
        self._last_seen.pop(control, None)
        self._last_logged.pop(control, None)
        if not self._last_seen:
            self._combined_logged = None
        logger.warning("%s control=%s — protection restored.", EVENT_RECOVERED, control)

    def degraded_controls(self) -> tuple[str, ...]:
        """Return the controls that reported degraded inside the window.

        Sorted, so callers and assertions get a stable order.
        """
        now = self._clock()
        return tuple(sorted(c for c, seen in self._last_seen.items() if now - seen <= self._window))

    def _maybe_report_combination(self, now: float) -> None:
        """Raise the louder event when more than one control is down at once."""
        active = self.degraded_controls()
        if len(active) < 2:
            return
        if not self._due(self._combined_logged, now):
            return
        self._combined_logged = now
        logger.critical(
            "%s controls=%s — brute-force protection and session revocation are "
            "not independent right now; one outage removed both.",
            EVENT_COMBINED,
            ",".join(active),
        )

    def _due(self, last: float | None, now: float) -> bool:
        """Whether enough time has passed since ``last`` to speak again."""
        return last is None or now - last >= self._cooldown


#: The process-wide ledger. Read it through the module-level functions below so
#: there is one place that resolves "which ledger", for the same reason
#: :func:`src.core.redis.get_redis` exists.
_ledger = DegradationLedger()


def report_degraded(control: str, *, detail: str) -> None:
    """Report a security control failing open.

    See :meth:`DegradationLedger.report_degraded`.
    """
    _ledger.report_degraded(control, detail=detail)


def report_healthy(control: str) -> None:
    """Report a security control working again.

    See :meth:`DegradationLedger.report_healthy`.
    """
    _ledger.report_healthy(control)


def degraded_controls() -> tuple[str, ...]:
    """Return the controls currently known to be failing open."""
    return _ledger.degraded_controls()
