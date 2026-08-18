"""Position probe against WB's public storefront search.

Answers "where does this SKU rank when a shopper types this phrase" — the one
question no seller API answers. The advertising surface reports the average
position of PAID impressions inside a cluster; the ranked organic list exists
only on the storefront, so this client reads the storefront.

**The session is the whole game.** WB's `wbaas` edge does not judge this request
by its IP, its headers, its HTTP version or its host — it judges whether the
caller carries a session it issued. Measured 2026-08-17 from the production VPS,
on its own datacenter address, no proxy:

* cookieless — **~1 request in 3 answered**, the rest 429, retries taking minutes;
* carrying a browser session — **10 of 10 answered, ~180 ms each**.

Everything else in this file's history was an attempt to fix that from the wrong
side: pacing, rotating residential proxies, fresh tunnels per request, flattened
retry ladders, three API versions. They each moved the number a little; the
session moved it to 100%. See :mod:`src.integrations.wildberries.search_session`
for how one is minted (a headless browser, once a day) and why one mint lasts.

Endpoint, verified 2026-08-17:

``GET https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search``

* This is the storefront's OWN route, which answers 403 to anyone without a
  session — the reason we used the bare ``search.wb.ru`` host until now.
* The version is load-bearing and WB retires versions without notice: v14 served
  full pages on 2026-08-14 and refused everything by 2026-08-17, from every IP,
  proxied or not, while v18 answered in the same minute. **A retired version is
  indistinguishable from a rate limit**, so when 429s become universal, check the
  version before blaming the network. It is a settings knob for that reason.
* Params are the storefront's own set (``lang``, ``locale``, ``hide_dtype``,
  ``hide_vflags``, ``inheritFilters``, ``suppressSpellcheck``, ``ab_testid``,
  plus ``dest``/``spp``/``resultset``/``sort``). Response keeps
  ``metadata.normquery`` and ``products[].id`` and **no longer carries `total`**,
  so an absent total means UNKNOWN, never "no results".
* ``metadata.normquery`` is WB's own normalization of the phrase and can reorder
  it («носки мужские» → «мужские носки»). It is the key the advertising clusters
  are filed under, which is what lets a live probe line up against them.
* A throttled request is **not always** a 429: the same phrase was answered 200
  with an ordinary envelope and zero products, then 100 products a minute later.
  An empty first page is therefore treated as a block, never as "ranks nowhere".

The pacing gate, the retry ladder and the proxy knob all remain, and all are now
fallbacks for a missing or expired session rather than the primary mechanism.

**What a position means, and does not.** The ranking is computed for the ``dest``
(delivery region) and ``spp`` (loyalty tier) sent with the request and moves
within the hour. A probe is a timestamped sample for one shopper profile, never a
stored fact.

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
from src.integrations.wildberries.search_session import SearchSession, load_session

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

    #: Headers the storefront's own SPA sends with this request, captured from a
    #: working browser call. Sent because the edge scores the whole shape of the
    #: request, and the ones it clearly reads are here: `x-requested-with`,
    #: `x-spa-version` and the `sec-*` group. The User-Agent is NOT here — it comes
    #: from the session, because the token embeds the UA it was minted with and a
    #: mismatched pair presents a session that contradicts itself.
    _HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "*/*",
        "Accept-Language": "ru,ru-RU;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.wildberries.ru/catalog/0/search.aspx",
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-requested-with": "XMLHttpRequest",
        "x-spa-version": "14.21.3",
        "x-userid": "0",
        "priority": "u=1, i",
    }

    @staticmethod
    def resolve_proxy(settings: Settings) -> str:
        """The forward proxy this client should use, or ``""`` for direct.

        DIRECT by default, and this setting has been round the houses: direct,
        then ``card`` (rotation being the only lever we had against what looked
        like an IP-reputation block), and direct again for a better reason than
        either — the block was never really about the IP. With a session, the
        VPS's own datacenter address answers 10 of 10 in ~180 ms; a residential
        exit buys nothing a session does not, and costs ~450 KB of billed traffic
        per page.

        ``card`` reuses ``wb_card_proxy`` (one credential, one place) if this host
        ever does start blocking us by address; any other value is a proxy URL.

        Args:
            settings: The application settings.

        Returns:
            The proxy URL, or an empty string for a direct connection.
        """
        configured = settings.wb_search_proxy.strip()
        if not configured or configured.casefold() == "direct":
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
            connect_timeout=settings.wb_search_connect_timeout_seconds,
            # A NEW tunnel per request, which is the whole point of a rotating
            # proxy: its exit IP changes per connection, so a pooled one pins
            # every retry to the address WB just refused. Measured 2026-08-17 —
            # one reused tunnel answered 1 of 4 requests, a fresh tunnel each
            # time answered 3 of 4.
            disable_keepalive=True,
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
            # `total` is absent from the current (v18) envelope, so 0 means
            # UNKNOWN, not "no results". Only a short page proves the result set
            # ran out; without that proof the safe claim is "there may be more",
            # because the alternative tells a seller their card is nowhere in WB
            # search when the scan simply stopped early.
            truncated=not exhausted and (total == 0 or total > scanned_slots),
            positions=sorted(found.values(), key=lambda position: position.position),
        )

    @staticmethod
    def _session_headers(session: SearchSession | None) -> dict[str, str] | None:
        """Cookie + UA headers for a stored session, or ``None`` without one.

        Anonymous is a supported state, not an error: WB answers roughly one such
        request in three, so a missing session degrades the probe instead of
        breaking it — and the ladder above exists for exactly that case.
        """
        if session is None:
            return None
        return {
            "Cookie": session.cookie_header,
            "User-Agent": session.user_agent,
            "deviceid": session.device_id,
        }

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
        # Captured from the storefront's own request on 2026-08-17. The extra
        # flags are free and remove differences between our call and one WB
        # serves without complaint; `lang`/`locale` in particular were absent
        # from every request of ours that got refused.
        params: dict[str, object] = {
            "ab_testid": "old_cb_and_poly",
            "appType": 1,
            "curr": "rub",
            "dest": self._dest,
            "hide_dtype": 15,
            "hide_vflags": 4294967296,
            "inheritFilters": "true",
            "lang": "ru",
            "locale": "ru",
            "resultset": "catalog",
            "sort": "popular",
            "spp": self._spp,
            "suppressSpellcheck": "false",
            "page": page,
            "limit": self._page_size,
            "query": query,
        }
        # Read per request rather than at construction: a client can outlive a
        # session (the minter refreshes daily), and a probe that started with the
        # old cookies would look throttled for reasons nothing logs.
        session = await load_session()
        headers = self._session_headers(session)
        try:
            payload = await self._request("GET", self._path, params=params, headers=headers)
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
