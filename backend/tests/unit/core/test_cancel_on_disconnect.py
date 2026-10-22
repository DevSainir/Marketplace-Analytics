"""An abandoned read stops computing; nothing else is touched.

The SPA aborts superseded requests, and without this middleware the API computes
every one of them to the end — several "All time" seq scans at once are
enough to slow the whole site. What is pinned: a GET whose client leaves
is cancelled and answered 499; a GET that finished is never cancelled, even by
the disconnect that ordinarily follows; a write is never cancelled at all.

That the cancellation reaches PostgreSQL and the connection comes back clean is
a property of asyncpg and SQLAlchemy beneath the request logger's cancel scope;
it was measured against a real server when this was written (see the module).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.core.disconnect import CLIENT_CLOSED_REQUEST, CancelOnDisconnect

pytestmark = pytest.mark.unit


class _Client:
    """The server side of one connection: what the app is told, what it sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._inbox.put_nowait({"type": "http.request", "body": b"", "more_body": False})

    def hang_up(self) -> None:
        """The browser aborts: the server reports a disconnect."""
        self._inbox.put_nowait({"type": "http.disconnect"})

    async def receive(self) -> dict[str, Any]:
        return await self._inbox.get()

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    def status(self) -> int | None:
        starts = [m for m in self.sent if m["type"] == "http.response.start"]
        return starts[0]["status"] if starts else None


class _SlowRead:
    """A handler that computes until told to stop, and records how it ended."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await receive()
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _scope(method: str) -> dict[str, Any]:
    return {"type": "http", "method": method, "path": "/api/v1/finreports/cost-prices"}


async def test_a_read_whose_client_left_is_cancelled_and_answered_499() -> None:
    """The browser aborted; the scan behind the request stops with it."""
    handler, client = _SlowRead(), _Client()
    request = asyncio.ensure_future(
        CancelOnDisconnect(handler)(_scope("GET"), client.receive, client.send)
    )
    await handler.entered.wait()

    client.hang_up()
    await asyncio.wait_for(request, timeout=1)

    assert handler.cancelled
    assert client.status() == CLIENT_CLOSED_REQUEST


async def test_a_read_that_finished_is_served_untouched() -> None:
    """The ordinary request: same status, same body, nothing cancelled."""
    handler, client = _SlowRead(), _Client()
    request = asyncio.ensure_future(
        CancelOnDisconnect(handler)(_scope("GET"), client.receive, client.send)
    )
    await handler.entered.wait()

    handler.release.set()
    await asyncio.wait_for(request, timeout=1)

    assert not handler.cancelled
    assert client.status() == 200
    assert client.sent[-1]["body"] == b"{}"


async def test_work_after_the_response_survives_the_closing_disconnect() -> None:
    """A disconnect after the last byte is the end of a request, not an abort.

    Background tasks run after the response is out, and the server reports the
    connection closed in exactly that window; cancelling there would kill them.
    """
    after_response = asyncio.Event()
    client = _Client()

    async def respond_then_work(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})
        client.hang_up()
        await asyncio.sleep(0.01)
        after_response.set()

    await asyncio.wait_for(
        CancelOnDisconnect(respond_then_work)(_scope("GET"), client.receive, client.send),
        timeout=1,
    )

    assert after_response.is_set()


async def test_a_write_is_never_cancelled_by_a_disconnect() -> None:
    """Whether a half-sent POST should still land is not the transport's call."""
    handler, client = _SlowRead(), _Client()
    request = asyncio.ensure_future(
        CancelOnDisconnect(handler)(_scope("POST"), client.receive, client.send)
    )
    await handler.entered.wait()

    client.hang_up()
    await asyncio.sleep(0.01)
    handler.release.set()
    await asyncio.wait_for(request, timeout=1)

    assert not handler.cancelled
    assert client.status() == 200
