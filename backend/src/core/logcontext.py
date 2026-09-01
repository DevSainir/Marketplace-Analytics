"""Who was asking, carried alongside every log line of one request (P2.2).

A log line that says `403` is a fact. A log line that says `403, this account,
this tenant, this request id` is an answer. The difference is what an incident
costs to investigate, and until now every line in this service was the first
kind: the request middleware knew the method and the path, the auth dependency
knew the user, the access guard knew the tenant, and none of them could see each
other.

Threading that through every call site was never going to happen — it would mean
a `context` argument on functions that have no business knowing about logging.
So it lives in a :mod:`contextvars` variable, which is what they are for: scoped
to a task, inherited by what it awaits, and **not shared between concurrently
running requests**. Two requests in flight on the same worker each see their own.

Why the variable holds a mutable dict
-------------------------------------
This is the part that is easy to get wrong, and it was: the obvious design is
one `ContextVar` per field, and it silently loses the most valuable field.

Starlette's `BaseHTTPMiddleware` — what `@app.middleware("http")` builds — runs
the downstream application in a **child task**. A child inherits a *copy* of the
parent's context, so values the middleware sets (request id, method, path) reach
the endpoint. But `ContextVar.set` in the child writes to the child's copy, so
values the endpoint learns — the account, the tenant, the two facts worth having
— never travel back up to the middleware that writes the request's summary line.
The line would come out with an id and a path and no idea who made the call, and
nothing would look broken.

Binding one mutable dict sidesteps it. The child inherits the same dict
*object*, so mutating it is visible to the parent; only rebinding would not be.
Hence: :func:`bind_request` binds a fresh dict, and everything after it mutates.

Set at the edges that learn each fact:

* :func:`bind_request` — the HTTP middleware, at the start of every request.
* :func:`bind_actor` — the auth dependency, once the token resolves.
* :func:`bind_tenant` — the access guard, once the membership resolves.

Everything else just logs, and the formatter attaches whatever is bound.

Nothing here is a security control by itself. What it is, is the thing that
makes the controls legible after the fact: P1.2's degradation events, P1.5's
backoff, the 401s and 403s of the guard ladder — all of them already fire, and
none of them could previously say *for whom*.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any

#: One mutable mapping per request — see the module docstring for why it is a
#: dict rather than a variable per field. ``None`` outside a request, which is
#: how the binders know to do nothing rather than invent a context.
_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "log_context", default=None
)


def new_request_id() -> str:
    """Return a fresh, short request identifier.

    Twelve hex characters rather than a full UUID: it is a correlation handle a
    human copies out of one line and greps for, not a key anything is stored
    under, and a 48-bit space is far beyond collision inside one log window.
    """
    return uuid.uuid4().hex[:12]


def bind_request(*, request_id: str, method: str, path: str, client_ip: str) -> None:
    """Start a context for this request and put the request's own facts in it.

    The one function here that *binds* rather than mutates. Everything after it
    adds to the dict this creates, which is what lets a fact learned deep in the
    request reach the line written at the end of it.

    Args:
        request_id: Correlation id for this request.
        method: HTTP method.
        path: Request path.
        client_ip: The address resolved by :mod:`src.core.client_ip` — the one
            nginx wrote, never one the caller chose.
    """
    _context.set(
        {
            "request_id": request_id,
            "method": method,
            "path": path,
            "client_ip": client_ip,
        }
    )


def _add(key: str, value: str | None) -> None:
    """Add one field to the live context, if there is one.

    Outside a request — a Celery task, a script, a test — there is no context
    and this does nothing. That is deliberate: inventing one here would produce
    a line that looks like it belongs to a request that never happened.
    """
    context = _context.get()
    if context is None or value is None:
        return
    context[key] = value


def bind_actor(user_id: uuid.UUID | None) -> None:
    """Attach the authenticated account, once the token has resolved.

    Args:
        user_id: The caller, or ``None`` to leave the field absent.
    """
    _add("user_id", str(user_id) if user_id is not None else None)


def bind_tenant(organization_id: uuid.UUID | None) -> None:
    """Attach the organisation the caller is acting in.

    Args:
        organization_id: The tenant, or ``None`` for a caller who has none yet
            (a fresh signup, an activation, an invitation acceptance).
    """
    _add("organization_id", str(organization_id) if organization_id is not None else None)


def current_context() -> dict[str, Any]:
    """Return everything bound for this task, or an empty mapping.

    A copy, so a formatter cannot accidentally mutate the request's context
    while rendering a line about it.

    Fields that were never bound are simply absent rather than ``null``, which
    keeps the absence meaningful: no ``user_id`` means nobody had authenticated
    yet, and that is itself the answer to some questions.
    """
    context = _context.get()
    return dict(context) if context else {}


def reset_context() -> None:
    """Drop the context entirely.

    For the end of a request and for Celery task boundaries. A worker reuses its
    process across tasks, so a context left bound would attribute the next
    task's lines to the previous task's tenant — and confidently wrong evidence
    is worse than none.
    """
    _context.set(None)


__all__ = [
    "bind_actor",
    "bind_request",
    "bind_tenant",
    "current_context",
    "new_request_id",
    "reset_context",
]
