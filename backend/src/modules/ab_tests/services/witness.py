"""Asking the storefront what photo is actually on the card.

The rotation records what it *installed*. Until this module existed nothing
checked what was *there*, and the gap is not hypothetical: on 2026-09-09 the
main photo of nm 1944299862 was rewritten at 11:58:18Z, thirteen hours after the
rotation's last install. Had that test still been running, every window after it
would have been credited to a variant the card was no longer showing, and
nothing on any screen would have said so. A wrong number that looks right is
this module's whole subject.

**The instrument is the CDN's own ``Last-Modified``.** Measured 2026-09-10: a
``POST /content/v3/media/file`` publishes in the second WB accepts it — all four
renditions of the new image carried the accept second, and a watcher saw the old
ETag at 07:44:54Z and the new one at 07:45:09Z. So the storefront's timestamp is
a faithful record of when the image last changed, precise to the second, and
comparing it against the one observed right after our own install answers «is
this still our photo» exactly rather than approximately.

Three properties that decide whether it can be trusted in a poller:

* **It costs nothing.** ``basket-NN.wbbasket.ru`` is public and unauthenticated
  and is not an API surface — no token, and not behind the Redis rate bucket
  every other WB call queues on. A HEAD per test per pass is free.
* **It is a HEAD, and the URL comes from our own database**, so it is validated
  against :func:`~src.integrations.wildberries.photos.is_wb_photo_url` before
  anything is fetched. An unchecked URL out of an upstream payload is SSRF, and
  that check is the one place in the codebase that says what a WB image URL is.
* **Every failure means «cannot check», never «mismatch».** An unreachable CDN,
  a card with no stored photo, a timestamp WB did not send: all of them return
  ``None``, and the caller must treat ``None`` as "carry on". A rotation that
  stopped itself because a CDN hiccuped would be a worse bug than the one this
  catches.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from src.core.logging import get_logger
from src.integrations.wildberries.photos import is_wb_photo_url

logger = get_logger(__name__)

#: Timeout for one HEAD against the CDN. Short on purpose: this is a check on
#: the way into a polling pass, not the pass's payload, and a hanging edge must
#: cost the pass a few seconds rather than its whole slot.
TIMEOUT_SECONDS: float = 5.0

#: How long to keep asking for a *changed* timestamp after an install, and how
#: often. Publication is same-second at the origin, but the read still has to
#: reach an edge that has it: the one measurement available saw the new ETag
#: about five seconds after the accept. Six tries two seconds apart covers that
#: with room to spare, and giving up stores ``None`` — «this install cannot be
#: vouched for» — rather than the stale value, which would read as a conflict on
#: the very next pass.
CONFIRM_ATTEMPTS: int = 6
CONFIRM_DELAY_SECONDS: float = 2.0


def _parse(header: str | None) -> datetime | None:
    """Turn an HTTP ``Last-Modified`` into an aware datetime, or ``None``.

    Args:
        header: The raw header value, or ``None`` when WB did not send one.

    Returns:
        The parsed moment, or ``None`` when it is absent or unparseable. A
        malformed date is not an error worth raising: it means the witness has
        nothing to say, which the caller already handles.
    """
    if not header:
        return None
    try:
        return parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None


class PhotoWitness:
    """Reads when the card's main photo was last published, from the storefront.

    Holds no session and no token: it is given a URL and asks the public CDN.
    The URL belongs to the caller because the module that owns the catalogue is
    monitoring, not this one — see the task wiring.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        confirm_delay: float = CONFIRM_DELAY_SECONDS,
    ) -> None:
        """Bind the witness to an HTTP client.

        Args:
            client: An async client the caller owns. Injected rather than
                created per call so one polling pass over many tests reuses one
                connection pool.
            confirm_delay: Seconds between the tries in
                :meth:`confirm_install`. Injected only so the unit tests can
                exercise the retry without sleeping through it — a test that
                waits ten seconds to prove an arithmetic property is a test
                somebody eventually deletes.
        """
        self._client = client
        self._confirm_delay = confirm_delay

    async def observe(self, photo_url: str) -> datetime | None:
        """When did the storefront last publish this image?

        Args:
            photo_url: The card's main photo on WB's CDN, as stored in
                monitoring's catalogue.

        Returns:
            The CDN's ``Last-Modified``, or ``None`` when it cannot be read —
            an empty or non-WB URL, a transport failure, a non-200, or a header
            WB did not send. Every one of those means «cannot check».
        """
        if not photo_url or not is_wb_photo_url(photo_url):
            return None
        try:
            response = await self._client.head(
                photo_url, timeout=TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.info("ab_tests: photo witness unreachable (%s); skipping the check", exc)
            return None
        if response.status_code != httpx.codes.OK:
            logger.info(
                "ab_tests: photo witness answered %s; skipping the check", response.status_code
            )
            return None
        return _parse(response.headers.get("last-modified"))

    async def confirm_install(self, photo_url: str, *, was: datetime | None) -> datetime | None:
        """Wait for the CDN to show OUR install, and return its timestamp.

        Called straight after WB accepts an upload. Reading once would race the
        edge — publication is same-second at the origin, but the value this
        process sees may still be the previous one for a few seconds, and
        storing that stale timestamp would make the very next pass report a
        conflict against our own photo.

        Args:
            photo_url: The card's main photo on WB's CDN.
            was: What the witness read BEFORE the install. The new timestamp is
                whatever differs from this. ``None`` means there was nothing to
                compare against, in which case the first reading is taken as
                the answer — there is no stale value to mistake it for.

        Returns:
            The published timestamp of our install, or ``None`` when it never
            changed within the bound. ``None`` disables the check for this turn
            rather than arming it with a value that is probably wrong.
        """
        for attempt in range(CONFIRM_ATTEMPTS):
            observed = await self.observe(photo_url)
            if observed is not None and observed != was:
                return observed
            if attempt < CONFIRM_ATTEMPTS - 1:
                await asyncio.sleep(self._confirm_delay)
        logger.info(
            "ab_tests: the CDN never moved off %s after an install; this turn is unwitnessed", was
        )
        return None


__all__ = ["CONFIRM_ATTEMPTS", "CONFIRM_DELAY_SECONDS", "TIMEOUT_SECONDS", "PhotoWitness"]
