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

#: The UA the session claims. Playwright's default announces
#: ``HeadlessChrome/131`` — a token minted under that UA was refused with 403 on
#: every request (measured 2026-08-18), which is the edge doing exactly what the
#: string invites. This is the same build's ordinary desktop UA, and because the
#: token embeds whatever UA minted it, the probe replays this one verbatim.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: Cookies a real storefront session carries. The token alone was not enough —
#: one cookie against a browser's eight also drew a 403 — so the mint waits for
#: the anti-bot JS to finish laying down the rest of its jar.
_REQUIRED_COOKIES = ("x_wbaas_token", "_wbauid")


async def mint() -> SearchSession | None:
    """Drive a headless browser until WB hands over a complete session.

    Returns:
        The minted session, or ``None`` when the challenge never completed.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            # --no-sandbox: the container runs unprivileged with no user
            # namespaces, and Chromium's sandbox needs them.
            # --disable-dev-shm-usage: Docker's default /dev/shm is 64 MB and
            # Chromium will exhaust it mid-navigation.
            # --disable-blink-features=AutomationControlled: drops the flag that
            # makes navigator.webdriver true, which is the cheapest tell there is.
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                viewport={"width": 1280, "height": 800},
            )
            # navigator.webdriver survives the launch flag in some builds; a real
            # Chrome never reports it.
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await context.new_page()
            await page.goto(
                _WARMUP_URL, wait_until="domcontentloaded", timeout=_CHALLENGE_TIMEOUT_MS
            )

            # Poll the jar rather than sleeping a fixed time: the challenge may
            # resolve in a second or take twenty. Wait for the WHOLE set — a jar
            # holding only the token was refused with 403 on every request.
            deadline = asyncio.get_running_loop().time() + _CHALLENGE_TIMEOUT_MS / 1000
            cookies: list[dict[str, object]] = []
            while asyncio.get_running_loop().time() < deadline:
                cookies = await context.cookies()
                names = {str(c.get("name")) for c in cookies}
                if all(required in names for required in _REQUIRED_COOKIES):
                    break
                await asyncio.sleep(1)

            jar = {str(c["name"]): str(c["value"]) for c in cookies}
            token = jar.get(_TOKEN_COOKIE, "")
            if not token:
                logger.error(
                    "No %s cookie after %.0fs.", _TOKEN_COOKIE, _CHALLENGE_TIMEOUT_MS / 1000
                )
                return None
            missing = [name for name in _REQUIRED_COOKIES if name not in jar]
            if missing:
                logger.warning("Session is missing %s; storing it anyway.", ", ".join(missing))

            expires_at = token_expiry(token)
            if expires_at is None:
                logger.error("Minted a %s that does not carry a readable expiry.", _TOKEN_COOKIE)
                return None

            device_id = jar.get("deviceid", "") or str(
                await page.evaluate("localStorage.getItem('deviceId') || ''")
            )
            return SearchSession(
                cookies=jar,
                user_agent=_USER_AGENT,
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
