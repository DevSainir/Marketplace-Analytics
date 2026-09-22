"""Customer-price client for the public WB storefront.

The public ``/cards/v4/detail`` endpoint is the only source for the *final
customer price* — what a shopper actually pays after ALL discounts, including
the WB loyalty discount (СПП). It is unauthenticated and returns prices in
kopecks.

**The host moved on 2026-09-22, and the old explanation of this file was
wrong.** Until then the endpoint lived at ``card.wb.ru`` and this module
explained its 403s by TLS fingerprinting and by datacenter-IP blocking. On
2026-09-22 ``card.wb.ru`` began answering 403 to *everything* — production
direct, production through a residential proxy, a laptop on a home line, and a
real Chrome — so neither explanation held any more: the host was simply closed.
The storefront now reads the same path through its own domain, found by reading
the SPA's own network log on a live product card:

    https://www.wildberries.ru/__internal/u-card/cards/v4/detail

What that move changed, all measured the same day (see
``.claude/skills/wildberries-api/references/storefront-card.md``):

* **One header gates it.** Sending each of the SPA's three headers alone,
  ``deviceid`` turns 403 into 200 while ``x-requested-with`` and
  ``x-spa-version`` change nothing. The value is arbitrary — a made-up one was
  accepted — so it is a required header, not a credential.
* **The envelope lost its wrapper**: ``products`` is at the top level now
  rather than under ``data``. :meth:`_fetch_batch` already read both.
* **``dest`` still selects a region**, and our historical value returns prices
  identical to the Moscow code the SPA sends, so the snapshot series continues
  unbroken. **``spp`` is ignored** — 0 and 30 return the same prices.

**What is still unresolved.** With ``deviceid`` but without a storefront
session, the edge answers **498** — the ``wbaas`` captcha page — from every
address we hold. A session token is a challenge response, and acquiring one is
not done here. So this client is correct against the endpoint and may still be
unable to reach it; the harvest already tolerates that (``card-prices`` is
recorded as a failed source and the customer price stays NULL for the day).

**Why this still shells out to ``curl``.** The original reason (a TLS
fingerprint filter that admitted the curl binary and refused Python's ``ssl``)
is no longer demonstrable: on the new host curl and httpx are refused
identically. Nothing measured says curl still helps — and nothing says it
hurts, so it stays until an experiment says otherwise, rather than being
swapped on a guess in the middle of an outage.

**Why an optional proxy.** It swapped the egress IP when the old host blocked
datacenter addresses. On the new host a residential exit gets the same 498 as
production's own address, so it is buying nothing today; it is left wired up
and empty-by-default rather than ripped out while the picture is still moving.

> Unofficial endpoint, used deliberately as the sole source of the post-loyalty
> customer price. Failures are tolerated by the harvest (the customer price /
> СПП just stay empty for the day).
"""

from __future__ import annotations

import asyncio
import json
import re
from types import TracebackType
from typing import Any, ClassVar, Self

from pydantic import ValidationError

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCardProduct

logger = get_logger(__name__)

#: Redacts ``user:password@`` credentials from a proxy URL before logging.
_CREDENTIALS_RE = re.compile(r"//[^/@\s]+@")


def _scrub(text: str) -> str:
    """Strip any ``user:pass@`` credentials from a string before it is logged."""
    return _CREDENTIALS_RE.sub("//***@", text)


class WBCardClient:
    """Fetches final customer prices from the WB storefront via a ``curl`` subprocess."""

    #: Max SKUs per detail request (the ``nm`` list is semicolon-separated). One
    #: large request beats many small ones over a slow proxy tunnel.
    _DETAIL_BATCH = 100

    #: Bounded fan-out over batches: fetch several concurrently (the proxy adds
    #: latency), but never flood a fragile tunnel.
    #:
    #: **Two, measured, not four.** The proxy caps concurrent CONNECTs, and past
    #: that cap it does not answer at all — the tunnel is never established and
    #: the request dies on `--connect-timeout`, or the provider refuses the
    #: CONNECT with its own `response 472`. Ten runs from the worker on
    #: 2026-09-07: sequential and 2-concurrent came back 200 in ~0.5-1.4 s;
    #: 4-concurrent lost one batch of four; 8-concurrent lost two and dragged
    #: two more out to 24-27 s. At four this cost a real seller 86 of 231
    #: customer prices on their first harvest — one whole batch, dropped after
    #: its retries, indistinguishable downstream from a SKU WB has no price for.
    _MAX_CONCURRENCY = 2

    #: Browser-like request headers, sent so the request looks like the WB
    #: storefront SPA. Measured 2026-09-22: none of these is what the endpoint
    #: gates on — ``deviceid`` (a setting, prepended in :meth:`_curl_get_json`)
    #: is. They are kept because they cost nothing and the SPA sends them.
    _HEADERS: ClassVar[tuple[str, ...]] = (
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept: application/json, text/plain, */*",
        "Accept-Language: ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin: https://www.wildberries.ru",
        "Referer: https://www.wildberries.ru/",
    )

    def __init__(self, settings: Settings) -> None:
        """Configure the client from application settings."""
        self._base_url = settings.wb_card_base_url.rstrip("/")
        self._path = "/" + settings.wb_card_path.lstrip("/")
        self._device_id = settings.wb_card_device_id
        self._dest = settings.wb_card_dest
        self._spp = settings.wb_card_spp
        self._proxy = settings.wb_card_proxy.strip()
        self._timeout = settings.wb_http_timeout_seconds
        self._connect_timeout = settings.wb_card_connect_timeout_seconds
        # Strict, dedicated retry cap for the proxy path (see module docstring).
        self._max_retries = settings.wb_card_max_retries
        self._backoff_base = settings.wb_retry_backoff_seconds
        self._backoff_max = settings.wb_retry_max_backoff_seconds

    async def __aenter__(self) -> Self:
        """Enter the async context (no persistent connection to manage)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the async context (nothing to close for a subprocess client)."""
        return

    async def aclose(self) -> None:
        """Symmetry with the httpx-based clients; a no-op here."""
        return

    async def fetch_customer_prices(self, nm_ids: list[int]) -> list[WBCardProduct]:
        """Fetch final customer prices for the given SKUs.

        Endpoint: ``GET`` on the configured storefront path (``wb_card_path``) with
        the storefront's own parameter set, ``dest`` from settings, and ``nm`` a
        semicolon-separated batch of SKU ids. Verified live shape (2026-07):
        ``{"data": {"products": [{id, sizes:[{price:{basic, product, ...}}]}]}}``
        with prices in kopecks (``product`` = final price after all discounts;
        there is no ``total`` in v4). SKUs are batched at :attr:`_DETAIL_BATCH`.

        Batches run concurrently (bounded by :attr:`_MAX_CONCURRENCY`) so the
        proxy's latency does not serialize. Resilience is per-batch: a batch
        that fails after its retries is dropped and logged, so a single dropped
        SKU-group never voids the whole harvest — BUT if EVERY batch fails
        (edge block, proxy down, or an API shape change caught by Pydantic),
        the error is raised so the harvest records the ``card-prices`` source as
        failed instead of silently writing zero customer prices.

        Args:
            nm_ids: SKU identifiers to fetch storefront prices for.

        Returns:
            One :class:`WBCardProduct` per SKU the storefront returned (only the
            successful batches when some batches failed).

        Raises:
            IntegrationError: When every batch failed.
        """
        if not nm_ids:
            return []

        batches = [
            nm_ids[offset : offset + self._DETAIL_BATCH]
            for offset in range(0, len(nm_ids), self._DETAIL_BATCH)
        ]
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)

        async def run(batch: list[int]) -> list[WBCardProduct]:
            async with semaphore:
                return await self._fetch_batch(batch)

        # ``return_exceptions`` isolates a flaky batch: gather never raises here,
        # so one dead tunnel does not abort the others.
        results = await asyncio.gather(*(run(batch) for batch in batches), return_exceptions=True)

        products: list[WBCardProduct] = []
        failures: list[BaseException] = []
        for result in results:
            if isinstance(result, BaseException):
                failures.append(result)
            else:
                products.extend(result)

        if failures and len(failures) == len(batches):
            # Total failure — surface it so the harvest skips the source loudly.
            raise IntegrationError(
                f"storefront card: all {len(batches)} batch(es) failed: {_scrub(str(failures[0]))}"
            )
        if failures:
            logger.warning(
                "storefront card: %d/%d batches failed and were dropped (%d products kept).",
                len(failures),
                len(batches),
                len(products),
            )
        return products

    async def _fetch_batch(self, batch: list[int]) -> list[WBCardProduct]:
        """Fetch and validate one SKU batch (``nm`` semicolon-joined).

        Raises:
            IntegrationError: On transport/retry exhaustion, an unexpected
                response envelope, or a Pydantic validation failure (an API
                shape change must surface, not corrupt the snapshot).
        """
        nm_param = ";".join(str(nm) for nm in batch)
        # Parameter order and set copied from the storefront's own request
        # (2026-09-22). ``nm`` stays LAST: it is the only variable part, which
        # keeps the URL greppable in logs and in tests.
        url = (
            f"{self._base_url}{self._path}"
            f"?appType=1&curr=rub&dest={self._dest}&spp={self._spp}"
            f"&hide_vflags=4294967296&hide_dflags=1048576&mtype=257"
            f"&lang=ru&ab_testing=false&nm={nm_param}"
        )
        payload = await self._curl_get_json(url)

        container = payload.get("data") if isinstance(payload, dict) else None
        rows = None
        if isinstance(container, dict):
            rows = container.get("products")
        elif isinstance(payload, dict):
            rows = payload.get("products")
        if not isinstance(rows, list):
            raise IntegrationError(
                "Unexpected card detail response shape (expected a products list)."
            )
        try:
            return [WBCardProduct.model_validate(row) for row in rows]
        except ValidationError as exc:
            # A storefront schema change: fail this batch (do NOT write partial
            # / wrong prices). If it changed for everyone, fetch_customer_prices
            # sees all batches fail and raises.
            raise IntegrationError(f"card detail row failed validation: {exc}") from exc

    async def _curl_get_json(self, url: str) -> Any:
        """GET ``url`` via a ``curl`` subprocess and return the decoded JSON.

        Retries transport failures / non-200 responses with exponential backoff,
        capped by the strict :attr:`_max_retries`. ``curl``'s TLS fingerprint is
        what clears the anti-bot edge; the optional ``--proxy`` swaps the egress
        IP (see the module docstring). Timeouts are strict so a dead proxy tunnel
        fails fast instead of burning the balance.

        Args:
            url: The fully-built card-detail URL.

        Returns:
            The decoded JSON payload.

        Raises:
            IntegrationError: On a non-200 response, unparseable body, or once
                retries are exhausted.
        """
        headers = (f"deviceid: {self._device_id}", *self._HEADERS)
        header_args: list[str] = [arg for header in headers for arg in ("-H", header)]
        proxy_args = ["-x", self._proxy] if self._proxy else []
        # ``-w '\n%{http_code}'`` appends the status after the body so we can
        # distinguish a 403 HTML page from a real JSON 200 without --fail
        # swallowing the body. ``--connect-timeout`` bounds the tunnel setup
        # separately from ``--max-time`` (the whole-request cap).
        args = [
            "curl",
            "-sS",
            *proxy_args,
            "--connect-timeout",
            str(int(self._connect_timeout)),
            "--max-time",
            str(int(self._timeout)),
            *header_args,
            "-w",
            "\n%{http_code}",
            url,
        ]

        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
            except OSError as exc:  # curl missing / not executable
                raise IntegrationError(
                    f"Unable to run curl for the storefront card endpoint: {exc}"
                ) from exc

            if proc.returncode == 0:
                text = stdout.decode("utf-8", "replace")
                body, _, status = text.rpartition("\n")
                if status.strip() == "200":
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError as exc:
                        last_error = f"non-JSON 200 body: {exc}"
                else:
                    last_error = f"HTTP {status.strip() or '???'}"
            else:
                # curl exit codes: proxy/connect/SSL/timeout failures land here
                # and are retried (bounded). Scrub any credentials curl echoed.
                last_error = _scrub(
                    stderr.decode("utf-8", "replace").strip() or "curl exited non-zero"
                )

            if attempt < self._max_retries:
                delay = min(self._backoff_base * (2.0**attempt), self._backoff_max)
                logger.warning(
                    "storefront card fetch failed (%s); retry %d/%d in %.1fs",
                    last_error,
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise IntegrationError(f"storefront card request failed: {last_error}.")
