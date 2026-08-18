"""Store a WB search session copied from the iOS app (or, failing that, a browser).

The token cannot be minted here — WB's challenge detects headless Chromium, which
is measured and written up in this repo's wildberries-api reference — so it is
copied. That takes about a minute, and the app's token is markedly better than the
website's:

* **iOS app** — a single ``X-Wbaas-Token`` header, no cookie jar, no proof of work
  (a subtractive bisect over the app's whole header set left only this and the
  User-Agent). Measured 2026-08-18 from the production VPS on its own datacenter
  IP: 20 of 20 requests answered, and it reaches the Russian catalogue through
  ``api-ios.wildberries.ru`` while restoring the ``total`` the website dropped.
* **website** — a cookie jar that answered 10 of 10 and was then revoked about
  half an hour into server-side use, dead afterwards even from the laptop that
  minted it.

Capture the app's request with a proxy on the phone (Proxyman, Charles), copy the
``X-Wbaas-Token`` header, and store it::

    WB_SEARCH_TOKEN='1.1000.…' \
    docker compose … exec -T api python -m scripts.set_search_session

The website form is still accepted::

    WB_SEARCH_COOKIE='external-locale=ru; _wbauid=…; x_wbaas_token=…' \
    WB_SEARCH_UA='Mozilla/5.0 (Macintosh; …) Chrome/151.0.0.0 Safari/537.36' \
    docker compose … exec -T api python -m scripts.set_search_session

The token declares its own expiry — 36 hours on the app samples — and the store
drops it when it lapses, so the panel falls back to anonymous probing (~1 request
in 3) rather than silently serving stale positions.
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

#: The app's own User-Agent, which its token is minted against. Defaulted so the
#: usual case is one variable to paste rather than two.
_IOS_USER_AGENT = (
    "Wildberries/7.7.6000 (RU.WILDBERRIES.MOBILEAPP; build:22862666; iOS 26.6.0) Alamofire/5.9.1"
)


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
    app_token = os.environ.get("WB_SEARCH_TOKEN", "").strip()
    cookie_header = os.environ.get("WB_SEARCH_COOKIE", "").strip()
    user_agent = os.environ.get("WB_SEARCH_UA", "").strip() or (
        _IOS_USER_AGENT if app_token else ""
    )
    if not user_agent or not (app_token or cookie_header):
        logger.error(
            "Set WB_SEARCH_TOKEN (iOS app, preferred) or WB_SEARCH_COOKIE (website); "
            "see this module's docstring."
        )
        return 2

    jar = parse_cookie_header(cookie_header) if cookie_header else {}
    token = app_token or jar.get("x_wbaas_token", "")
    if not token:
        logger.error("Neither an app token nor an x_wbaas_token cookie was given.")
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
            wbaas_token=app_token,
        )
    )
    hours = (expires_at - datetime.now(UTC)).total_seconds() / 3600
    logger.info(
        "Stored %s; good for %.1f h.",
        "an app token" if app_token else f"{len(jar)} cookies",
        hours,
    )
    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
