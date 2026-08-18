"""Unit tests for the WB storefront session store.

No Redis and no browser: what these pin is the reasoning the rest of the feature
leans on — that a token declares its own expiry, that a nearly-expired one is
refused before a scan starts, and that an unreadable one is treated as "no
session" rather than "never expires".
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from src.integrations.wildberries.search_session import SearchSession, token_expiry


def _token(*, expires: int, issued: int = 1787069215) -> str:
    """Build an x_wbaas_token whose payload carries the given timestamps."""
    payload = "|".join(
        [
            "0",
            "198.51.100.21",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/151.0.0.0",
            str(expires),
            "reusable",
            "2",
            "eyJoYXNoIjoiIn0=",
            "0",
            "3",
            str(issued),
            "1",
        ]
    )
    encoded = base64.b64encode(payload.encode()).decode().rstrip("=")
    return f"1.1000.ecc264cf20a343248f9653c0002a16fd.{encoded}.MEQCIBDLSEOwbFIE"


def test_the_token_declares_its_own_expiry() -> None:
    """Read, not assumed: the store's TTL and the refusal margin both depend on it.

    The real token observed on 2026-08-17 was issued for 36 hours, which is what
    makes minting a daily job instead of a per-request one.
    """
    expires = int(datetime(2026, 8, 20, 4, 6, 55, tzinfo=UTC).timestamp())

    assert token_expiry(_token(expires=expires)) == datetime(2026, 8, 20, 4, 6, 55, tzinfo=UTC)


def test_a_token_of_an_unexpected_shape_has_no_expiry() -> None:
    """`None` means "unusable". Defaulting to "never expires" would serve a dead
    session forever, and every probe would look throttled with nothing to log."""
    assert token_expiry("not-a-token") is None
    assert token_expiry("1.1000.deadbeef") is None


def test_a_session_expiring_within_the_margin_is_refused() -> None:
    """A scan started at the edge can outlive its token mid-flight.

    "Expired halfway" is indistinguishable from being throttled, so the margin
    keeps that case out of the data instead of leaving it to be debugged.
    """
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    nearly_done = SearchSession(
        cookies={"x_wbaas_token": "…"},
        user_agent="Chrome",
        device_id="site_x",
        expires_at=now + timedelta(minutes=5),
    )
    plenty = SearchSession(
        cookies={"x_wbaas_token": "…"},
        user_agent="Chrome",
        device_id="site_x",
        expires_at=now + timedelta(hours=10),
    )

    assert nearly_done.is_usable(now=now) is False
    assert plenty.is_usable(now=now) is True


def test_cookies_render_as_one_header() -> None:
    """The client sends the whole jar: a session missing half of itself looks
    synthetic to the edge that issued it."""
    session = SearchSession(
        cookies={"_wbauid": "87005", "x_wbaas_token": "1.1000.abc"},
        user_agent="Chrome",
        device_id="site_x",
        expires_at=datetime.now(UTC) + timedelta(hours=10),
    )

    assert session.cookie_header == "_wbauid=87005; x_wbaas_token=1.1000.abc"
