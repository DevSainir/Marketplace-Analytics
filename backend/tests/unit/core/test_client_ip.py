"""Unit tests for the client-address resolution the auth rate limiter keys on.

The behaviour under test is a security control, not a convenience: a limiter
keyed on ``request.client.host`` gets what uvicorn derives from the leftmost
``X-Forwarded-For`` entry while running in always-trust mode. With nginx
appending to that header rather than replacing it, any client could choose its
own counter key and brute-force ``/login`` without limit.

These cases pin the two halves of the fix: the address nginx wrote wins, and
anything that is not an IP address never reaches a Redis key.
"""

from __future__ import annotations

from fastapi import Request

from src.core.client_ip import UNKNOWN_CLIENT, resolve_client_ip


def _request(*, headers: dict[str, str] | None = None, peer: str | None = "10.0.0.9") -> Request:
    """Build a minimal ASGI request with the fields the resolver reads.

    Args:
        headers: Request headers to expose, ASCII-encoded as ASGI expects.
        peer: The immediate peer address, or ``None`` for no client at all.

    Returns:
        A request object carrying just that scope.
    """
    raw = [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": raw,
            "client": (peer, 51234) if peer is not None else None,
        }
    )


def test_the_address_nginx_wrote_is_used() -> None:
    """``X-Real-IP`` is the signal, because nginx replaces it from $remote_addr."""
    request = _request(headers={"X-Real-IP": "203.0.113.7"})

    assert resolve_client_ip(request) == "203.0.113.7"


def test_a_spoofed_forwarded_chain_cannot_choose_the_key() -> None:
    """A client-supplied ``X-Forwarded-For`` loses to the proxy's own header.

    This is that bypass in miniature. ``peer`` here stands in for what
    uvicorn's always-trust mode already resolved from the leftmost forwarded
    entry — attacker-chosen — and it must not become the counter key.
    """
    request = _request(
        headers={"X-Forwarded-For": "198.51.100.1", "X-Real-IP": "203.0.113.7"},
        peer="198.51.100.1",
    )

    assert resolve_client_ip(request) == "203.0.113.7"


def test_a_header_that_is_not_an_address_is_refused() -> None:
    """Free text never reaches the counter key, so keys cannot be minted at will.

    Were this accepted, a different junk value per request would buy a fresh
    budget every time — the same bypass by another route — and would put
    attacker text into the request log.
    """
    request = _request(headers={"X-Real-IP": "not-an-ip; DROP"}, peer="10.0.0.9")

    assert resolve_client_ip(request) == "10.0.0.9"


def test_the_peer_is_used_when_no_proxy_header_is_present() -> None:
    """Local development has no nginx, and still needs a per-client budget."""
    request = _request(peer="127.0.0.1")

    assert resolve_client_ip(request) == "127.0.0.1"


def test_one_ipv6_address_gets_one_budget_however_it_is_spelled() -> None:
    """Equivalent IPv6 spellings normalise to a single counter key."""
    verbose = _request(headers={"X-Real-IP": "2001:0db8:0000:0000:0000:0000:0000:0001"})
    compact = _request(headers={"X-Real-IP": "2001:db8::1"})

    assert resolve_client_ip(verbose) == resolve_client_ip(compact)


def test_an_unidentifiable_caller_falls_back_to_a_shared_bucket() -> None:
    """No header and no peer yields one shared key, not a private budget each.

    Fail-closed by design: callers we cannot tell apart should throttle each
    other rather than each be handed a fresh allowance.
    """
    request = _request(peer=None)

    assert resolve_client_ip(request) == UNKNOWN_CLIENT
