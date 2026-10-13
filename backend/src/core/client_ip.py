"""Who a request actually came from, resolved behind the reverse proxy.

nginx is the only ingress — the API port is never published — and it sets
``X-Real-IP`` from its own ``$remote_addr``. (Behind the edge since 2026-10,
``$remote_addr`` is the address in the edge's PROXY protocol header, not the
edge's own: ``real_ip_header proxy_protocol`` in nginx.conf, held there by
``tests/unit/core/test_edge_ingress.py``.) ``proxy_set_header`` *replaces*
whatever arrived, so a client cannot influence that header. It is therefore the
one client-address signal on the request that a security control may key on.

``request.client`` is **not** that signal. uvicorn runs with
``--forwarded-allow-ips "*"``, which puts its proxy middleware in always-trust
mode; there it takes the **leftmost** ``X-Forwarded-For`` entry. A client that
sends its own ``X-Forwarded-For`` therefore chooses ``request.client.host``,
which until this module was the key of the auth rate limiter — an unlimited
password brute-force for the price of one header (register item P0.1).

The peer address stays as the fallback so local development, where nothing sets
``X-Real-IP``, still gets a per-client budget rather than one global bucket.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from fastapi import Request

#: Header nginx fills from ``$remote_addr`` — see ``snippets/proxy-headers.conf``.
REAL_IP_HEADER = "x-real-ip"

#: Bucket for requests whose origin cannot be established. Deliberately a single
#: shared key: callers we cannot tell apart should throttle each other rather
#: than each receive a private budget.
UNKNOWN_CLIENT = "unknown"


def resolve_client_ip(request: Request) -> str:
    """Return the originating client address as a normalised IP string.

    Args:
        request: The incoming request.

    Returns:
        The client's IP in its canonical form, or :data:`UNKNOWN_CLIENT` when
        neither the proxy header nor the peer address yields a valid address.
    """
    from_proxy = _as_ip_address(request.headers.get(REAL_IP_HEADER))
    if from_proxy is not None:
        return from_proxy
    peer = request.client.host if request.client else None
    return _as_ip_address(peer) or UNKNOWN_CLIENT


def _as_ip_address(value: str | None) -> str | None:
    """Normalise a candidate address, rejecting anything that is not an IP.

    Validation is not cosmetic: the result becomes part of a Redis key and a log
    line, so accepting free text would let a client mint unlimited counter keys
    (each one a fresh budget) and inject into the log.

    Args:
        value: Raw header or peer value, possibly ``None``.

    Returns:
        The address in :mod:`ipaddress` canonical form, or ``None`` when it does
        not parse — which also collapses the many spellings of one IPv6 address
        onto a single counter.
    """
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Who the caller appears to be, for the row that records a session.

    Two fields with very different standing, and the difference is the reason
    this is one object rather than two parameters.

    ``ip_address`` is resolved by :func:`resolve_client_ip`, which is the only
    client-address signal on the request a control may key on. ``user_agent`` is
    the opposite: a header the client writes and may put anything in. It is
    stored verbatim and never parsed here — the SPA turns it into «Chrome на
    macOS», and a value it cannot make sense of is shown as nothing rather than
    guessed at. Nothing authorises on it.
    """

    ip_address: str
    user_agent: str | None


def resolve_client_info(request: Request) -> ClientInfo:
    """Build the provenance stamp for a session row from one request.

    Args:
        request: The incoming request.

    Returns:
        The address and the raw User-Agent, the latter truncated to what the
        column can hold so an oversized header cannot fail the login it
        accompanies.
    """
    agent = request.headers.get("user-agent")
    return ClientInfo(
        ip_address=resolve_client_ip(request),
        user_agent=agent[:400] if agent else None,
    )
