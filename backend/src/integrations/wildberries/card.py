"""Customer-price client for the public WB storefront (card.wb.ru).

The public ``card.wb.ru`` detail endpoint is the only source for the *final
customer price* — what a shopper actually pays after ALL discounts, including the
WB loyalty discount (СПП). It is unauthenticated and returns prices in kopecks.

**Why this client shells out to ``curl`` instead of using httpx.** The endpoint
is fronted by WB's anti-bot edge (``wbaas``), which fingerprints the TLS
ClientHello and returns HTTP 403 to Python's ``ssl``-module fingerprint (httpx,
requests, even curl-impersonate signatures) while admitting a real ``curl``
binary — verified live: identical headers, same egress IP, curl → 200, httpx →
403. Header/HTTP-version spoofing does not help; only the genuine curl TLS
fingerprint clears the filter. So this one endpoint is fetched via a ``curl``
subprocess. ``curl`` is installed in the app + worker images.

> Unofficial endpoint, used deliberately as the sole source of the post-loyalty
> customer price. Failures are tolerated by the harvest (the customer price /
> СПП just stay empty for the day).
"""

from __future__ import annotations

import asyncio
import json
from types import TracebackType
from typing import Any, ClassVar, Self

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCardProduct

logger = get_logger(__name__)


class WBCardClient:
    """Fetches final customer prices from card.wb.ru via a ``curl`` subprocess."""

    #: Max SKUs per detail request (the ``nm`` list is semicolon-separated).
    _DETAIL_BATCH = 100

    #: Browser-like request headers. These do NOT clear the anti-bot filter on
    #: their own (the TLS fingerprint does — see the module docstring); they are
    #: sent for good measure so the request looks like the WB storefront SPA.
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
        self._dest = settings.wb_card_dest
        self._spp = settings.wb_card_spp
        self._timeout = settings.wb_http_timeout_seconds
        self._max_retries = settings.wb_max_retries
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
        return None

    async def aclose(self) -> None:
        """Symmetry with the httpx-based clients; a no-op here."""
        return None

    async def fetch_customer_prices(self, nm_ids: list[int]) -> list[WBCardProduct]:
        """Fetch final customer prices for the given SKUs.

        Endpoint: ``GET /cards/v4/detail`` with ``curr=rub``, ``dest`` (region
        code) and ``spp`` (loyalty tier) from settings, and ``nm`` a
        semicolon-separated batch of SKU ids. Verified live shape (2026-07):
        ``{"data": {"products": [{id, sizes:[{price:{basic, product, ...}}]}]}}``
        with prices in kopecks (``product`` = final price after all discounts;
        there is no ``total`` in v4). SKUs are batched at :attr:`_DETAIL_BATCH`.

        Args:
            nm_ids: SKU identifiers to fetch storefront prices for.

        Returns:
            One :class:`WBCardProduct` per SKU the storefront returned.
        """
        products: list[WBCardProduct] = []
        for offset in range(0, len(nm_ids), self._DETAIL_BATCH):
            batch = nm_ids[offset : offset + self._DETAIL_BATCH]
            nm_param = ";".join(str(nm) for nm in batch)
            url = (
                f"{self._base_url}/cards/v4/detail"
                f"?curr=rub&dest={self._dest}&spp={self._spp}&nm={nm_param}"
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
            products.extend(WBCardProduct.model_validate(row) for row in rows)
        return products

    async def _curl_get_json(self, url: str) -> Any:
        """GET ``url`` via a ``curl`` subprocess and return the decoded JSON.

        Retries transport failures / non-200 responses with exponential backoff,
        mirroring the httpx clients' resilience. ``curl``'s TLS fingerprint is
        what clears the anti-bot edge (see the module docstring).

        Args:
            url: The fully-built card-detail URL.

        Returns:
            The decoded JSON payload.

        Raises:
            IntegrationError: On a non-200 response, unparseable body, or once
                retries are exhausted.
        """
        header_args: list[str] = []
        for header in self._HEADERS:
            header_args += ["-H", header]
        # ``-w '\n%{http_code}'`` appends the status after the body so we can
        # distinguish a 403 HTML page from a real JSON 200 without --fail
        # swallowing the body.
        args = [
            "curl",
            "-sS",
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
                raise IntegrationError(f"Unable to run curl for card.wb.ru: {exc}") from exc

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
                last_error = stderr.decode("utf-8", "replace").strip() or "curl exited non-zero"

            if attempt < self._max_retries:
                delay = min(self._backoff_base * (2.0**attempt), self._backoff_max)
                logger.warning(
                    "card.wb.ru fetch failed (%s); retry %d/%d in %.1fs",
                    last_error,
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise IntegrationError(f"card.wb.ru request failed: {last_error}.")
