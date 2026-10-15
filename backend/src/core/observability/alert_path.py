"""What ``/healthz/alerts`` checks: whether an alert raised now would reach Telegram.

Every other check in this service can only report a problem by sending an alert,
so none of them can report that alerts themselves stopped going out. On
2026-09-29 that was the whole incident: ``ServerErrorRate`` fired, Telegram was
unreachable from the box and had been for two weeks, and a customer told us.
The only witness that can notice a silent pager is one outside the box, so this
route exists to be polled from there — by UptimeRobot, the same app that already
pushes to the owner's phone when ``/healthz`` stops answering.

What it asks, and why that one question is enough
-------------------------------------------------
It asks Alertmanager whether the ``Watchdog`` alert is active. ``Watchdog``
(``docker/observability/alerts.yml``, group ``meta``) is a rule that fires for
as long as the alert path is healthy, so its presence in Alertmanager is the
conjunction of every link in that path:

* Prometheus is alive and evaluating rules — it re-sends a firing alert every
  minute, and Alertmanager lets it lapse about four minutes after the last one;
* Prometheus can reach Alertmanager, and Alertmanager is up;
* the rule's own condition: no Telegram delivery has failed for 30 minutes and
  the relay still has a road to Telegram.

Keeping the definition of "healthy" in the rule rather than here is deliberate.
The rule is evaluated whether or not anybody polls this route, it is what the
Grafana dashboard shows, and a second definition in Python would drift from it.

What it says back
-----------------
``alerts-ok`` or ``alerts-down`` and nothing else — this is a public route, and
the reason it failed (a host, a timeout, an HTTP status from an internal
service) belongs in the log. UptimeRobot watches it as a keyword monitor on
``alerts-ok``, so anything else it could ever see — an nginx error page, the
SPA's fallback HTML for a path nginx does not route — reads as down.

What a flood costs
------------------
Nothing upstream: the answer is cached for :data:`CACHE_SECONDS`, so however
often a stranger asks, Alertmanager is asked at most once per window per API
process. The checker polls every five minutes; a fifteen-second-old answer is
fresh to it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

#: The heartbeat rule's name in ``alerts.yml``.
WATCHDOG: Final[str] = "Watchdog"

#: How long one answer is reused. See "What a flood costs" above.
CACHE_SECONDS: Final[float] = 15.0

#: Budget for the call to Alertmanager. It is on the same Docker network and
#: answers in a millisecond; two seconds is the readiness probe's own budget,
#: chosen for the same reason — a hung dependency must produce a fast "down".
_TIMEOUT_SECONDS: Final[float] = 2.0


@dataclass(frozen=True, slots=True)
class _Answer:
    healthy: bool
    at: float


class AlertPathProbe:
    """Asks Alertmanager about ``Watchdog`` and remembers the answer briefly.

    Args:
        base_url: Alertmanager's address, e.g. ``http://alertmanager:9093``.
        transport: The HTTP transport; tests pass an ``httpx.MockTransport``.
        clock: A monotonic clock in seconds; tests pass a fake one.
    """

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/v2/alerts"
        self._transport = transport
        self._clock = clock
        self._last: _Answer | None = None

    async def healthy(self) -> bool:
        """Whether alerts are getting out, as of at most :data:`CACHE_SECONDS` ago.

        Never raises: a probe that raised would answer 500, and the checker
        would read that as "down" anyway — but through the error path, which
        logs a traceback per poll instead of one line saying what was wrong.
        """
        now = self._clock()
        if self._last is not None and now - self._last.at < CACHE_SECONDS:
            return self._last.healthy
        healthy = await self._ask()
        self._last = _Answer(healthy=healthy, at=now)
        return healthy

    async def _ask(self) -> bool:
        params = {
            # Suppressed counts as down: a silenced heartbeat is one nobody is
            # hearing, which is the condition this route exists to report.
            "active": "true",
            "silenced": "false",
            "inhibited": "false",
            "filter": f'alertname="{WATCHDOG}"',
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(self._url, params=params)
            response.raise_for_status()
            alerts = response.json()
        except Exception as exc:
            # Every exception, for the reason `health._timed` gives: whatever
            # broke — DNS (the stack is not running), a refused connection, a
            # timeout, a 5xx, a body that is not JSON — the fact for the
            # checker is the same one.
            logger.warning(
                "Alert path check could not ask Alertmanager: %s: %s", type(exc).__name__, exc
            )
            return False
        if _watchdog_firing(alerts):
            return True
        logger.warning("Alert path check: Watchdog is not firing, so alerts are not getting out.")
        return False


def _watchdog_firing(alerts: object) -> bool:
    """Whether Alertmanager's answer contains an active ``Watchdog``.

    Checked here as well as asked for in the query, because the query filters
    are Alertmanager's to honour: an answer listing some other alert, or a
    suppressed Watchdog, must not read as healthy.
    """
    if not isinstance(alerts, list):
        return False
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        labels, status = alert.get("labels"), alert.get("status")
        if (
            isinstance(labels, dict)
            and isinstance(status, dict)
            and labels.get("alertname") == WATCHDOG
            and status.get("state") == "active"
        ):
            return True
    return False


_probe = AlertPathProbe(settings.alertmanager_url)


async def alerts_getting_out() -> bool:
    """The process-wide probe behind ``/healthz/alerts``."""
    return await _probe.healthy()


__all__ = ["CACHE_SECONDS", "WATCHDOG", "AlertPathProbe", "alerts_getting_out"]
