"""Position probe against the public WB search host (search.wb.ru).

Answers "where does this SKU rank when a shopper types this phrase" — the one
question no seller API answers. The advertising surface reports the average
position of PAID impressions inside a search cluster; the ranked organic list
exists only on the storefront, so this client reads the storefront.

Verified live 2026-08-14 against ``GET /exactmatch/ru/common/v14/search``:

* The API **version is load-bearing**. ``v14`` served full result pages while
  ``v13`` and ``v5`` answered HTTP 429 to every request from the same IP in the
  same minute — a retired version fails as if you were rate-limited. It is a
  settings knob for exactly that reason.
* Params: ``query``, ``page`` (1-based), ``limit`` (100 = what the storefront
  itself asks for), plus ``dest``, ``spp``, ``resultset=catalog``, ``sort``,
  ``appType``, ``curr``. Response: ``{"metadata": {"normquery": ...},
  "products": [...], "total": N}``, ``products`` in rank order.
* **Throttled per IP, hard.** Back-to-back requests answer 429 even one per
  25 s; ~1/min was sustainable. Pages are therefore fetched one at a time AND
  paced by a shared Redis token bucket (:func:`search_rate_gate`) — sequential
  is not the same as paced, and for a while this client only managed the former:
  three pages left in the same second, which tripped the edge on the probe's own
  first page and left the next press inside the penalty window. The depth is
  bounded by settings and the caller caches the result.
* A throttled request is **not always** a 429: the same query was answered HTTP
  200 with an ordinary envelope, zero products and ``total: 0``, then 100
  products and ``total: 109542`` a minute later. An empty first page is
  therefore rejected rather than reported as "ranks nowhere".
* ``metadata.normquery`` is WB's own normalization of the phrase and can reorder
  it («носки мужские» → «мужские носки»). It is the same key the advertising
  clusters carry, which is what lets a live probe be lined up against them.
* Unlike ``card.wb.ru``, this host does **not** need curl's TLS fingerprint —
  ``httpx`` was served 200s (including one 220 KB page) in the same session in
  which ``curl`` was being 429'd, so this rides the normal async client.

**Why it does NOT go through the card proxy.** It briefly did, on the assumption
that this host shares card.wb.ru's block on datacenter egress (403 there since
2026-07-14). Measured from the production VPS on 2026-08-15, the same query
seconds apart, that assumption was wrong in the worst way: **direct answered 200
with a full page while the residential proxy answered 429.** This edge does not
block our address, it rate-limits per IP — and a shared proxy exit arrives with
that budget already spent by somebody else. Proxying made throttling MORE likely
and cost ~216 KB of billed traffic per page. Default is direct;
``WB_SEARCH_PROXY=card`` opts back in if this host ever starts blocking us too
(see :meth:`WBPublicSearchClient.resolve_proxy`).

**What a position means, and does not.** The ranking is computed for the
``dest`` (delivery region) and ``spp`` (loyalty tier) sent with the request and
moves within the hour. A probe is a timestamped sample for one shopper profile,
never a stored fact — which is why nothing here is persisted.

> Unofficial endpoint, used deliberately: it is the only source of organic
> position. A failure degrades the panel, never the harvest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import ValidationError

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import search_rate_gate
from src.integrations.wildberries.schemas import WBSearchPage

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SearchPosition:
    """Where one SKU was found in the scanned results."""

    nm_id: int
    #: 1-based rank across every scanned page (page 2, slot 3 at 100 per page is
    #: position 103) — the number a seller means by «позиция».
    position: int
    page: int
    position_on_page: int


@dataclass(frozen=True, slots=True)
class SearchProbe:
    """The outcome of one keyword probe.

    ``truncated`` says WB has results the probe never looked at, so a SKU absent
    from ``positions`` means "not within the scanned depth" rather than "not in
    WB search".
    """

    query: str
    normalized_query: str
    total_found: int
    pages_scanned: int
    positions_scanned: int
    truncated: bool
    positions: list[SearchPosition]


class WBPublicSearchClient(BaseWBClient):
    """Reads ranked pages from WB's public search and locates given SKUs."""

    #: Headers the WB storefront SPA sends. The endpoint answered without them
    #: too, but an unadorned API-client signature is the first thing an anti-bot
    #: edge filters on (card.wb.ru already blocks one), so they are sent.
    _HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.wildberries.ru",
        "Referer": "https://www.wildberries.ru/",
    }

    @staticmethod
    def resolve_proxy(settings: Settings) -> str:
        """The forward proxy this client should use, or ``""`` for direct.

        Direct by default, unlike ``card.wb.ru``. Measured from the production
        VPS on 2026-08-15, the same query seconds apart: **direct answered 200
        with a full page while the residential proxy answered 429.** This host
        does not block datacenter egress — it rate-limits per IP, and a shared
        proxy exit has already spent that budget on somebody else. Proxying here
        therefore made throttling more likely AND cost ~216 KB of billed traffic
        per page.

        ``card`` opts back into ``wb_card_proxy`` (one credential, one place) if
        this host ever starts blocking us the way the card endpoint does; any
        other value is used as the proxy URL.

        Args:
            settings: The application settings.

        Returns:
            The proxy URL, or an empty string for a direct connection.
        """
        configured = settings.wb_search_proxy.strip()
        if not configured:
            return ""
        if configured.casefold() == "card":
            return settings.wb_card_proxy.strip()
        return configured

    def __init__(self, settings: Settings, *, patient: bool = False) -> None:
        """Build the unauthenticated storefront-search client.

        No token: the storefront needs none. What makes a probe
        workspace-specific is which SKUs the caller asks it to look for.

        Args:
            settings: The application settings.
            patient: Use the SCHEDULED run's retry budget instead of the
                interactive one. A background run has no one watching, so
                outlasting several throttle windows beats returning early with
                nothing; a watched request must answer or say why. Same host,
                opposite trade — measured, see ``wb_search_task_max_retries``.
        """
        retries = settings.wb_search_task_max_retries if patient else settings.wb_search_max_retries
        backoff = (
            settings.wb_search_task_retry_backoff_seconds
            if patient
            else settings.wb_search_retry_backoff_seconds
        )
        ceiling = (
            settings.wb_search_task_retry_max_backoff_seconds
            if patient
            else settings.wb_search_retry_max_backoff_seconds
        )
        super().__init__(
            base_url=settings.wb_search_base_url,
            token="",
            timeout=settings.wb_search_timeout_seconds,
            # The probe's own, much tighter ladder — NOT the seller APIs'. See
            # ``wb_search_max_retries``: a watched request must fail fast and be
            # retried into a warm cache, not sit through WB's throttle window.
            max_retries=retries,
            backoff_base_seconds=backoff,
            backoff_max_seconds=ceiling,
            # Without this, one ``Retry-After: 60`` from WB reinstates exactly
            # the latency the budget above exists to bound: a demanded wait is
            # otherwise honoured past the backoff cap.
            retry_after_ceiling_seconds=ceiling,
            proxy=self.resolve_proxy(settings),
            # The gate is what makes this client survivable. Its pages used to
            # go out back-to-back, which tripped the edge on the probe's own
            # first page; the gate is consulted before EVERY attempt, retries
            # included, and is shared by the api and worker processes because WB
            # meters the IP they share.
            rate_gate=search_rate_gate(settings),
            extra_headers=self._HEADERS,
        )
        self._path = settings.wb_search_path
        self._dest = settings.wb_search_dest
        self._spp = settings.wb_card_spp
        self._page_size = settings.wb_search_page_size
        self._max_pages = settings.wb_search_max_pages

    async def find_positions(
        self, *, query: str, nm_ids: set[int], max_pages: int | None = None
    ) -> SearchProbe:
        """Scan the first pages of WB search for ``query`` and locate ``nm_ids``.

        Pages are fetched **sequentially**: the host 429s back-to-back requests,
        so fanning out would trade a slow answer for no answer. The scan stops
        early once every requested SKU is located, and as soon as WB returns a
        short (final) page.

        A page that fails after its retries ends the scan instead of raising —
        the positions already found are real, and the caller learns the depth
        actually reached from ``pages_scanned``. The FIRST page is the exception:
        if it fails, nothing was learned, and the error must surface rather than
        be reported as "your SKU is nowhere".

        Args:
            query: The shopper's phrase, as typed.
            nm_ids: The SKUs to look for (the workspace's catalogue).
            max_pages: Lower the configured page budget (never raises it).

        Returns:
            The probe outcome, positions ordered best first.

        Raises:
            IntegrationError: When the very first page could not be read.
        """
        budget = self._max_pages if max_pages is None else min(max_pages, self._max_pages)
        wanted = set(nm_ids)
        found: dict[int, SearchPosition] = {}
        normalized = ""
        total = 0
        scanned_pages = 0
        scanned_slots = 0
        exhausted = False

        for page in range(1, budget + 1):
            try:
                result = await self._fetch_page(query=query, page=page)
            except IntegrationError:
                if page == 1:
                    raise
                logger.warning(
                    "search.wb.ru: stopping the probe for %r after page %d (page %d failed).",
                    query,
                    page - 1,
                    page,
                )
                break

            scanned_pages = page
            if page == 1:
                normalized = result.metadata.norm_query
                total = result.total
            for slot, product in enumerate(result.products, start=1):
                scanned_slots += 1
                if product.nm_id in wanted and product.nm_id not in found:
                    found[product.nm_id] = SearchPosition(
                        nm_id=product.nm_id,
                        position=scanned_slots,
                        page=page,
                        position_on_page=slot,
                    )
            if len(result.products) < self._page_size:
                # WB ran out of results: another page would return nothing.
                exhausted = True
                break
            if wanted and len(found) == len(wanted):
                break

        return SearchProbe(
            query=query,
            normalized_query=normalized,
            total_found=total,
            pages_scanned=scanned_pages,
            positions_scanned=scanned_slots,
            truncated=not exhausted and total > scanned_slots,
            positions=sorted(found.values(), key=lambda position: position.position),
        )

    async def _fetch_page(self, *, query: str, page: int) -> WBSearchPage:
        """Fetch and validate one ranked result page.

        Args:
            query: The shopper's phrase.
            page: 1-based page number.

        Returns:
            The parsed page.

        Raises:
            IntegrationError: On retry exhaustion, an unexpected envelope, a
                payload that no longer matches the verified shape, or a page 1
                that is empty while WB reports results (a soft block).
        """
        params: dict[str, object] = {
            "ab_testing": "false",
            "appType": 1,
            "curr": "rub",
            "dest": self._dest,
            "resultset": "catalog",
            "sort": "popular",
            "spp": self._spp,
            "page": page,
            "limit": self._page_size,
            "query": query,
        }
        try:
            payload = await self._request("GET", self._path, params=params)
        except IntegrationError as exc:
            # The probe gives up fast by design (see the retry budget in
            # settings), so retry exhaustion here is the ORDINARY throttled
            # outcome, not a breakage — and it has to read that way to whoever
            # pressed the button. Wrapped at the transport call, not around the
            # whole page fetch, so the soft-block message below (which says
            # something more specific) survives untouched. The transport detail
            # stays as the cause, for the log.
            raise IntegrationError(
                f"search.wb.ru не ответил на проверку позиции по запросу {query!r} — "
                "публичный поиск сейчас ограничивает частоту запросов. "
                "Повторите через минуту."
            ) from exc
        if not isinstance(payload, dict):
            raise IntegrationError(
                "Unexpected search response shape (expected an object, "
                f"got {type(payload).__name__})."
            )
        try:
            parsed = WBSearchPage.model_validate(payload)
        except ValidationError as exc:
            raise IntegrationError(f"search page failed validation: {exc}") from exc
        if page == 1 and not parsed.products:
            # Verified live: a THROTTLED request is answered HTTP 200 with an
            # ordinary metadata envelope, zero products and total 0 — the same
            # phrase served 100 products and total=109542 a minute later. There
            # is no field that separates that from a phrase WB genuinely finds
            # nothing for, so an empty first page is never passed through as a
            # result: reporting it would tell the seller every SKU is unranked.
            raise IntegrationError(
                f"search.wb.ru вернул пустую выдачу по запросу {query!r} — "
                "либо WB притормозил запрос, либо по этой фразе ничего не находится. "
                "Повторите проверку через минуту."
            )
        return parsed
