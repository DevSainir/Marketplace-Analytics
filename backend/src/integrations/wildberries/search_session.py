"""The WB session the public search requires, stored in Redis.

WB's storefront edge (``wbaas``) does not judge a search request by its IP, its
headers or its HTTP version — it judges whether the caller carries a session it
issued. Measured 2026-08-17 from the production VPS, on its own datacenter
address and with no proxy:

* cookieless, every variation we could think of — **~1 request in 3 answered**,
  the rest 429, with waits of minutes;
* carrying a real browser session — **10 of 10 answered, ~180 ms each**.

That is the whole difference, and it is why nothing else moved the needle.

**What a session is.** A handful of cookies, of which ``x_wbaas_token`` is the
load-bearing one. Its payload is base64 and self-describing::

    0|198.51.100.21|Mozilla/5.0 (Macintosh…)|1787198815|reusable|…|1787069215|1
      ^ issuing IP      ^ issuing User-Agent   ^ expires  ^ reusable  ^ issued

Two properties make this design possible, both verified rather than assumed:

* **``reusable``, and valid for 36 hours.** One mint serves tens of thousands of
  requests, so acquiring it is a daily job, not a per-request one.
* **The IP is recorded, not enforced.** The same token answered 200 from the
  laptop that minted it (198.51.100.20), and from the VPS (203.0.113.10).
  It was predicted to fail there; it did not.

The User-Agent, though, must match the one the token was minted with — it is part
of the payload — so the session carries its UA and the client sends it back.

**The app's token is the one that works.** Two surfaces issue this token and they
are not equivalent in practice (measured 2026-08-18 from the production VPS):

* the WEBSITE's cookie session answered 10 of 10 at ~180 ms — and was then
  revoked about half an hour into server-side use, dead afterwards even from the
  laptop whose browser minted it;
* the iOS APP's ``X-Wbaas-Token`` answered 20 of 20 with nothing else attached
  but a User-Agent, and is under a longer watch.

The app's is also far cheaper to carry: no cookie jar, no device id, no
proof-of-work — a subtractive bisect over the app's full header set showed
``X-Wbaas-Token`` is the only header the edge insists on. (``X-Pow`` is not, which
was a surprise worth recording.) It reaches the Russian catalogue through
``api-ios.wildberries.ru`` and even restores the ``total`` the website dropped.

**Why Redis.** The token outlives any one process, and the api and the worker both
need it. A restart must not cost a re-copy, and losing it is survivable: without a
session the probe falls back to the anonymous host and its ~1-in-3 odds.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.exceptions import RedisError

from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)

#: One key, workspace-independent: the session identifies our CLIENT to WB, not
#: any seller. Every workspace's probes ride the same one.
_SESSION_KEY = "monitoring:wb-search-session"

#: Refuse a token with less than this left. A probe that starts inside the last
#: minutes of validity can outlive it mid-scan, and "expired halfway" is the one
#: failure mode a caller cannot distinguish from being throttled.
_EXPIRY_MARGIN_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class SearchSession:
    """A WB session, from either the website or the iOS app.

    The two surfaces present the same token differently: the site keeps it in a
    ``x_wbaas_token`` COOKIE, the app sends it as the ``X-Wbaas-Token`` HEADER.
    The app's is the one worth having — see the module docstring.

    Attributes:
        cookies: Cookie name → value (website sessions).
        wbaas_token: The token as a bare string (app sessions), sent as a header.
        user_agent: The UA the token was minted with. Part of the token payload,
            so a different one presents a session that contradicts itself.
        device_id: The client's own device id, sent alongside a website session.
        expires_at: When the token stops being accepted, read from its payload.
    """

    cookies: dict[str, str]
    user_agent: str
    device_id: str
    expires_at: datetime
    wbaas_token: str = ""

    @property
    def cookie_header(self) -> str:
        """The cookies as one ``Cookie:`` header value."""
        return "; ".join(f"{name}={value}" for name, value in self.cookies.items())

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Whether the token has enough life left to start a scan with.

        Args:
            now: Override the clock (tests).

        Returns:
            True when it expires more than the safety margin from now.
        """
        moment = now or datetime.now(UTC)
        return (self.expires_at - moment).total_seconds() > _EXPIRY_MARGIN_SECONDS


def token_expiry(token: str) -> datetime | None:
    """Read the expiry out of an ``x_wbaas_token``.

    The token is dot-separated and its third segment is base64 holding
    pipe-separated fields; field 3 is the expiry as a Unix timestamp. Parsed
    rather than assumed so a stored session knows its own lifetime and nothing
    has to guess "probably a day".

    Args:
        token: The raw cookie value.

    Returns:
        The expiry, or ``None`` when the token is not in the expected shape —
        which is treated as "unusable", never as "never expires".
    """
    parts = token.split(".")
    if len(parts) < 4:
        return None
    try:
        payload = base64.b64decode(parts[3] + "==").decode("utf-8", "replace")
        fields = payload.split("|")
        return datetime.fromtimestamp(int(fields[3]), UTC)
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


async def load_session() -> SearchSession | None:
    """Return the stored session, or ``None`` when there is none worth using.

    Returns:
        The session, or ``None`` when absent, unreadable, or too close to
        expiry. A ``None`` here is not an error: the probe falls back to an
        anonymous request, which WB answers roughly a third of the time.
    """
    try:
        raw = await get_redis().get(_SESSION_KEY)
    except RedisError:
        logger.warning("Redis unavailable: probing WB search without a session.")
        return None
    if raw is None:
        return None
    payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        stored = json.loads(payload)
        session = SearchSession(
            cookies=dict(stored["cookies"]),
            user_agent=str(stored["user_agent"]),
            device_id=str(stored.get("device_id", "")),
            expires_at=datetime.fromisoformat(stored["expires_at"]),
            wbaas_token=str(stored.get("wbaas_token", "")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("Stored WB search session is unreadable; ignoring it.")
        return None
    if not session.is_usable():
        logger.warning("Stored WB search session expires at %s; ignoring it.", session.expires_at)
        return None
    return session


async def store_session(session: SearchSession) -> None:
    """Persist a freshly minted session for every process to use.

    The Redis TTL is the token's own remaining life, so an expired session
    disappears on its own rather than being served to a probe that will then look
    throttled for reasons nothing logs.

    Args:
        session: The session to store.
    """
    ttl = int((session.expires_at - datetime.now(UTC)).total_seconds())
    if ttl <= 0:
        logger.warning("Refusing to store an already-expired WB search session.")
        return
    body = json.dumps(
        {
            "cookies": session.cookies,
            "user_agent": session.user_agent,
            "device_id": session.device_id,
            "expires_at": session.expires_at.isoformat(),
            "wbaas_token": session.wbaas_token,
        }
    )
    try:
        await get_redis().set(_SESSION_KEY, body, ex=ttl)
    except RedisError:
        logger.warning("Redis unavailable: the minted WB search session was not stored.")
        return
    logger.info(
        "Stored a WB search session valid until %s (%.1f h).",
        session.expires_at,
        ttl / 3600,
    )
