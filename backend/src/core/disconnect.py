"""Stop computing a read nobody is waiting for any more.

The SPA aborts a superseded request — a period switched twice, a page left
before it loaded — and the browser drops the connection. Nothing told the API:
uvicorn reports a disconnect only to a handler that asks for one, and ours never
ask, so an abandoned «Вся история» kept its seq scan running to the end. Several
at once on a two-core box with 384 MiB for Postgres is what slowed every other
page four- to eightfold on 2026-10-05.

This middleware listens for the disconnect on the handler's behalf and cancels
it. The cancellation reaches the database: asyncpg answers a cancelled
``await`` by sending PostgreSQL a cancel request for the running statement, and
:func:`~src.core.deps.get_db` rolls the transaction back under a shield, so the
connection goes back to the pool clean.

**Innermost, not outermost — and that is the part that matters.** The request
logger is a ``BaseHTTPMiddleware``, which runs everything beneath it inside an
anyio cancel scope. Cancel the request from outside that scope and anyio
re-delivers the cancellation at every ``await`` that follows, including the
ones SQLAlchemy needs to hand the connection back: the pool gives up
terminating it, the statement runs to its end on the server, and the
connection is lost. Tried that way first and measured on a real Postgres
(2026-10-09). Inside the scope, the handler is a task of our own, cancelled
once, and asyncio's one-shot cancellation lets the cleanup finish.

It then answers 499, nginx's "client closed request", to a client that is no
longer there. Nobody reads it; the request log and the HTTP metrics do, and
that is how an abandoned request is told apart from a served one.

**Reads only — GET and HEAD.** A cancelled write would be rolled back too, but
whether a half-sent POST should still land is a product decision per route, not
a transport one; and a GET carries no body, which is what lets the middleware
take the request message off the wire itself and keep listening. Once the last
byte of the response is out, a disconnect is the ordinary end of a request and
cancels nothing — background tasks still run.
"""

from __future__ import annotations

import asyncio
import contextlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: nginx's code for a request whose client hung up first.
CLIENT_CLOSED_REQUEST = 499

_READS: frozenset[str] = frozenset({"GET", "HEAD"})


class CancelOnDisconnect:
    """Cancel a read's handler when its client goes away mid-computation."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the request, racing it against the client's disconnect."""
        if scope["type"] != "http" or scope["method"] not in _READS:
            await self.app(scope, receive, send)
            return

        request = await receive()
        if request.get("more_body", False):
            # A read with a streamed body: not ours to take apart.
            await self.app(scope, _replay(request, receive), send)
            return

        gone = asyncio.Event()
        started = False
        finished = False
        pending: Message | None = request

        async def app_receive() -> Message:
            nonlocal pending
            if pending is not None:
                message, pending = pending, None
                return message
            await gone.wait()
            return {"type": "http.disconnect"}

        async def app_send(message: Message) -> None:
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        async def watch() -> None:
            if request["type"] != "http.disconnect":
                while (await receive())["type"] != "http.disconnect":
                    pass
            gone.set()

        handler = asyncio.ensure_future(self.app(scope, app_receive, app_send))
        watcher = asyncio.ensure_future(watch())
        try:
            await asyncio.wait({handler, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if gone.is_set() and not finished and not handler.done():
                handler.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handler
                if not started:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": CLIENT_CLOSED_REQUEST,
                            "headers": [],
                        }
                    )
                    await send({"type": "http.response.body", "body": b""})
                return
            await handler
        finally:
            watcher.cancel()
            if not handler.done():
                handler.cancel()
            # A watcher that failed rather than heard a disconnect cancels
            # nothing; its error is collected so asyncio does not report it.
            if watcher.done() and not watcher.cancelled():
                watcher.exception()


def _replay(first: Message, receive: Receive) -> Receive:
    """A ``receive`` that hands back an already-read message before the rest."""
    pending: Message | None = first

    async def replayed() -> Message:
        nonlocal pending
        if pending is not None:
            message, pending = pending, None
            return message
        return await receive()

    return replayed


__all__ = ["CLIENT_CLOSED_REQUEST", "CancelOnDisconnect"]
