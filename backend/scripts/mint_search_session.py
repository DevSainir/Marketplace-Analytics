"""Mint a WB storefront session with a headless browser, and store it.

WB's `wbaas` edge issues its session token from JavaScript, which is the one
thing an HTTP client cannot do — and carrying that token is the difference
between roughly one search request in three being answered and all of them
(measured 2026-08-17: 10/10 at ~180 ms, against ~1/3 with minutes of retries).

So a browser runs once a day, loads the storefront like a shopper, waits for the
challenge to settle, and hands the resulting cookies to Redis for every process
to use. The token says ``reusable`` and lives 36 hours, so this is a daily job
rather than a per-request one: tens of thousands of probes ride one mint.

Run it from the repository root on the server::

    docker compose --project-directory backend -f backend/docker/docker-compose.yml \
        run --rm -T session_minter

Exit codes: 0 minted and stored, 1 the challenge never produced a token.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from playwright.async_api import async_playwright

from src.core.logging import configure_logging, get_logger
from src.integrations.wildberries.search_session import (
    SearchSession,
    store_session,
    token_expiry,
)

logger = get_logger(__name__)

#: Name of the cookie the edge actually checks (a name, not a secret — the value
#: never appears in this file). Everything else in the jar is carried along
#: because a session missing half of itself looks synthetic.
_TOKEN_COOKIE = "x_wbaas_token"  # noqa: S105 — a cookie NAME, not a credential

#: A search results page, not the home page: the token is issued for the surface
#: being used, and this is the one our probes call.
_WARMUP_URL = (
    "https://www.wildberries.ru/catalog/0/search.aspx?search=%D0%BD%D0%BE%D1%81%D0%BA%D0%B8"
)

#: How long to give the JS challenge. It normally settles in a few seconds; the
#: ceiling is here so a hung run cannot hold the container all night.
_CHALLENGE_TIMEOUT_MS = 60_000


async def mint() -> SearchSession | None:
    """Drive a headless browser until WB hands over a session.

    Returns:
        The minted session, or ``None`` when no token appeared in time.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            # --no-sandbox: the container runs unprivileged with no user
            # namespaces, and Chromium's sandbox needs them. --disable-dev-shm-usage
            # because Docker's default /dev/shm is 64 MB and Chromium will
            # cheerfully exhaust it and crash mid-navigation.
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(locale="ru-RU")
            page = await context.new_page()
            await page.goto(
                _WARMUP_URL, wait_until="domcontentloaded", timeout=_CHALLENGE_TIMEOUT_MS
            )

            # Poll the jar rather than sleeping a fixed time: the challenge may
            # resolve in a second or take twenty, and a fixed wait is either a
            # waste or a flake.
            deadline = asyncio.get_running_loop().time() + _CHALLENGE_TIMEOUT_MS / 1000
            token = ""
            cookies: list[dict[str, object]] = []
            while asyncio.get_running_loop().time() < deadline:
                cookies = await context.cookies()
                token = next(
                    (str(c["value"]) for c in cookies if c.get("name") == _TOKEN_COOKIE), ""
                )
                if token:
                    break
                await asyncio.sleep(1)

            if not token:
                logger.error(
                    "No %s cookie after %.0fs.", _TOKEN_COOKIE, _CHALLENGE_TIMEOUT_MS / 1000
                )
                return None

            expires_at = token_expiry(token)
            if expires_at is None:
                logger.error("Minted a %s that does not carry a readable expiry.", _TOKEN_COOKIE)
                return None

            user_agent = str(await page.evaluate("navigator.userAgent"))
            # The storefront's own device id, minted alongside the session and
            # sent as a header with every search call.
            device_id = next(
                (str(c["value"]) for c in cookies if c.get("name") == "deviceid"),
                "",
            ) or str(await page.evaluate("localStorage.getItem('deviceId') || ''"))

            return SearchSession(
                cookies={str(c["name"]): str(c["value"]) for c in cookies},
                user_agent=user_agent,
                device_id=device_id,
                expires_at=expires_at,
            )
        finally:
            await browser.close()


async def main() -> int:
    """Mint a session, store it, and report what was obtained."""
    configure_logging()
    session = await mint()
    if session is None:
        return 1
    await store_session(session)
    hours = (session.expires_at - datetime.now(UTC)).total_seconds() / 3600
    logger.info(
        "Minted a WB search session: %d cookies, valid %.1f h (until %s).",
        len(session.cookies),
        hours,
        session.expires_at,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
