"""The question behind ``/healthz/alerts``: is ``Watchdog`` active in Alertmanager?

The route is the only witness to a silent pager (2026-09-29: Telegram unreachable
for two weeks, learned from a customer), so the two ways it can lie are what
these tests pin. It must never say "ok" unless an *active* ``Watchdog`` is in
the answer — a suppressed one, some other alert, an error page or a timeout all
mean nobody would hear an alert. And a public route must not turn a stranger's
flood into a flood on Alertmanager.

Unit tier: Alertmanager is an ``httpx.MockTransport`` and the clock is a number.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.observability.alert_path import CACHE_SECONDS, AlertPathProbe

pytestmark = pytest.mark.unit


def _alert(name: str = "Watchdog", state: str = "active") -> dict[str, Any]:
    """One entry of Alertmanager's ``GET /api/v2/alerts``, as the live one answers."""
    return {
        "labels": {"alertname": name, "severity": "heartbeat"},
        "status": {"state": state, "silencedBy": [], "inhibitedBy": [], "mutedBy": []},
        "receivers": [{"name": "watchdog"}],
    }


class _Alertmanager:
    """A fake Alertmanager: answers with whatever ``reply`` returns, counts calls."""

    def __init__(self, reply: Callable[[httpx.Request], httpx.Response]) -> None:
        self.calls = 0
        self._reply = reply

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return self._reply(request)

        return httpx.MockTransport(handle)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _probe(alertmanager: _Alertmanager, clock: _Clock | None = None) -> AlertPathProbe:
    return AlertPathProbe(
        "http://alertmanager:9093",
        transport=alertmanager.transport(),
        clock=clock or _Clock(),
    )


async def test_an_active_watchdog_means_alerts_are_getting_out() -> None:
    """The one answer that may read as healthy."""
    alertmanager = _Alertmanager(lambda _: httpx.Response(200, json=[_alert()]))

    healthy = await _probe(alertmanager).healthy()

    assert healthy is True


async def test_no_watchdog_means_alerts_are_not_getting_out() -> None:
    """The rule stopped firing: a Telegram send failed, or Prometheus is gone."""
    alertmanager = _Alertmanager(lambda _: httpx.Response(200, json=[]))

    healthy = await _probe(alertmanager).healthy()

    assert healthy is False


async def test_a_silenced_watchdog_is_not_a_heartbeat() -> None:
    """Somebody silenced it, so its absence would never be noticed — that is down.

    Asked for in the query too, but the query filters are Alertmanager's to
    honour; the answer is checked here regardless.
    """
    alertmanager = _Alertmanager(lambda _: httpx.Response(200, json=[_alert(state="suppressed")]))

    healthy = await _probe(alertmanager).healthy()

    assert healthy is False


async def test_some_other_alert_in_the_answer_is_not_a_heartbeat() -> None:
    """A firing ``ServerErrorRate`` proves Alertmanager is up, not that it delivers."""
    alertmanager = _Alertmanager(
        lambda _: httpx.Response(200, json=[_alert(name="ServerErrorRate")])
    )

    healthy = await _probe(alertmanager).healthy()

    assert healthy is False


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(lambda _: httpx.Response(503, text="unavailable"), id="5xx"),
        pytest.param(lambda _: httpx.Response(200, text="<html>not json</html>"), id="not-json"),
        pytest.param(lambda _: httpx.Response(200, json={"alerts": []}), id="wrong-shape"),
        pytest.param(lambda _: httpx.Response(200, json=[{"labels": "x"}]), id="junk-entry"),
    ],
)
async def test_an_answer_that_is_not_a_list_of_alerts_reads_as_down(
    reply: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Whatever Alertmanager says, only a well-formed active Watchdog is "ok"."""
    alertmanager = _Alertmanager(reply)

    healthy = await _probe(alertmanager).healthy()

    assert healthy is False


async def test_an_unreachable_alertmanager_reads_as_down_without_raising() -> None:
    """The monitoring stack is not running: nothing would deliver an alert.

    It must come back as ``False`` rather than an exception, so the route answers
    its own 503 instead of a 500 with a traceback per poll.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    healthy = await _probe(_Alertmanager(refuse)).healthy()

    assert healthy is False


async def test_the_query_asks_only_for_an_active_unsilenced_watchdog() -> None:
    """What is asked decides what "ok" means, so the filter is part of the contract."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[_alert()])

    await _probe(_Alertmanager(record)).healthy()

    params = seen[0].url.params
    assert seen[0].url.path == "/api/v2/alerts"
    assert params["filter"] == 'alertname="Watchdog"'
    assert params["active"] == "true"
    assert params["silenced"] == "false"
    assert params["inhibited"] == "false"


async def test_a_flood_reaches_alertmanager_once_per_window() -> None:
    """A public route must not relay a stranger's request rate to an internal service."""
    alertmanager = _Alertmanager(lambda _: httpx.Response(200, json=[_alert()]))
    probe = _probe(alertmanager)

    for _ in range(50):
        await probe.healthy()

    assert alertmanager.calls == 1


async def test_after_the_window_the_answer_is_asked_again() -> None:
    """A cached "ok" must not outlive the outage that follows it by more than a window."""
    answers = iter([[_alert()], []])
    alertmanager = _Alertmanager(lambda _: httpx.Response(200, json=next(answers)))
    clock = _Clock()
    probe = _probe(alertmanager, clock)
    await probe.healthy()
    clock.now += CACHE_SECONDS

    healthy = await probe.healthy()

    assert healthy is False
