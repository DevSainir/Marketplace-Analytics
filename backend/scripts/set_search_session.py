"""Store a WB storefront session copied from a real browser.

The automated mint does not work, and the reason is not fixable from our side:
WB's `wbaas` challenge detects headless Chromium itself. Measured 2026-08-18 from
the production VPS — datacenter IP, residential proxy exit, hardened fingerprint
(spoofed UA, locale, timezone, viewport, webdriver, plugins, WebGL vendor) — every
attempt was served HTTP 498 «Подозрительная активность» and a placeholder token
that every later request refuses with 403. A real browser on the same residential
network is served normally.

So the session is copied from a browser instead, which takes about thirty seconds
every few days:

1. Open wildberries.ru, search for anything.
2. DevTools → Network → the `u-search` request → Copy → Copy as cURL.
3. Paste the ``-b '…'`` cookie string and the ``user-agent`` header here::

       WB_SEARCH_COOKIE='external-locale=ru; _wbauid=…; x_wbaas_token=…' \\
       WB_SEARCH_UA='Mozilla/5.0 (Macintosh; …) Chrome/151.0.0.0 Safari/537.36' \\
       docker compose … run --rm -T api python -m scripts.set_search_session

The token declares its own expiry — 72 hours on the samples seen so far — and the
store drops it when it lapses, so the panel degrades to anonymous probing (~1
request in 3) rather than silently serving stale positions.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from src.core.logging import configure_logging, get_logger
from src.integrations.wildberries.search_session import (
    SearchSession,
    store_session,
    token_expiry,
)

logger = get_logger(__name__)


def parse_cookie_header(raw: str) -> dict[str, str]:
    """Split a ``Cookie:`` header value into its pairs.

    Args:
        raw: The header value, as copied from DevTools.

    Returns:
        Cookie name → value, in the order given.
    """
    jar: dict[str, str] = {}
    for chunk in raw.split(";"):
        name, _, value = chunk.strip().partition("=")
        if name and value:
            jar[name] = value
    return jar


async def main() -> int:
    """Read the pasted session from the environment and store it."""
    configure_logging()
    cookie_header = os.environ.get("WB_SEARCH_COOKIE", "").strip()
    user_agent = os.environ.get("WB_SEARCH_UA", "").strip()
    if not cookie_header or not user_agent:
        logger.error("Set WB_SEARCH_COOKIE and WB_SEARCH_UA (see this module's docstring).")
        return 2

    jar = parse_cookie_header(cookie_header)
    token = jar.get("x_wbaas_token", "")
    if not token:
        logger.error("The cookie string carries no x_wbaas_token; nothing to store.")
        return 2

    expires_at = token_expiry(token)
    if expires_at is None:
        logger.error("That x_wbaas_token carries no readable expiry; refusing to store it.")
        return 2
    if expires_at <= datetime.now(UTC):
        logger.error("That session expired at %s; copy a fresh one.", expires_at)
        return 2

    await store_session(
        SearchSession(
            cookies=jar,
            user_agent=user_agent,
            device_id=jar.get("deviceid", ""),
            expires_at=expires_at,
        )
    )
    hours = (expires_at - datetime.now(UTC)).total_seconds() / 3600
    logger.info("Stored %d cookies; the session is good for %.1f h.", len(jar), hours)
    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
