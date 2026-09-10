"""Asynchronous WildBerries Advertising client (campaign stats & listings).

Injects the workspace's Promotion-scope bearer token and returns *typed raw*
payloads (:mod:`src.integrations.wildberries.schemas`). All network I/O is
async via ``httpx.AsyncClient`` inherited from :class:`BaseWBClient`.
"""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import advertising_rate_gate
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBCampaign,
    WBCampaignGroup,
    WBNormQueryItem,
)

# NOTE on shape validation: a 200 response whose body does not match the
# verified live shape (WB error envelope, silent contract change) must raise
# IntegrationError — defaulting to an empty list would let the harvest report
# "success" with zero rows, silently punching holes in the time series.


class WBAdvertisingClient(BaseWBClient):
    """Client for the WB Advertising surface (campaign full stats)."""

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the advertising client.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's Promotion-scope bearer token.
        """
        super().__init__(
            base_url=settings.wb_advertising_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            # Two consumers share this token — the nightly harvest and the A/B
            # rotation poller — and fullstats allows one request per 20s. The
            # gate is Redis-backed so they queue against ONE budget instead of
            # finding each other through 429s.
            rate_gate=advertising_rate_gate(settings, token=token),
        )

    #: Max campaign ids per fullstats request (WB caps the ``ids`` list).
    _FULLSTATS_BATCH = 50

    async def fetch_full_stats(
        self,
        *,
        campaign_ids: list[int],
        date_from: date,
        date_to: date,
    ) -> list[WBAdvCampaignStats]:
        """Fetch full advertising statistics for one or more campaigns.

        Endpoint: ``GET /adv/v3/fullstats``.

        Verified against the live WB API (2026-07): the query parameters are
        ``ids`` (comma-separated campaign ids), ``beginDate`` and ``endDate`` in
        ``YYYY-MM-DD`` format. Campaign ids are requested in batches of
        :attr:`_FULLSTATS_BATCH`; the response is a list with one entry per
        campaign that had activity in the window. Live constraints:

        * WB **does** serve current-day statistics, and the counters are
          cumulative since Moscow midnight. (This docstring said the opposite
          until 2026-09-10, when a 20-second probe found all 29 intervals
          gaining — see the ``wildberries-api`` skill. The rotation poller in
          ``ab_tests`` has been reading today all along; the note was stale,
          not the behaviour.) A reading can go *down* as WB restates a recent
          day, so a difference between two readings must be clamped at zero.
        * The maximum window is 31 days, and this surface is aggressively
          rate-limited — 3 requests per minute, one token per 20 s, per seller
          token, shared with every other consumer through
          :func:`~src.integrations.wildberries.rate_limit.advertising_rate_gate`.

        Args:
            campaign_ids: WB campaign identifiers (``ids`` param).
            date_from: Inclusive start date (Moscow time).
            date_to: Inclusive end date (Moscow time); must be <= yesterday.

        Returns:
            One :class:`WBAdvCampaignStats` per campaign that returned data.
        """
        results: list[WBAdvCampaignStats] = []
        for start in range(0, len(campaign_ids), self._FULLSTATS_BATCH):
            batch = campaign_ids[start : start + self._FULLSTATS_BATCH]
            params: dict[str, object] = {
                "ids": ",".join(str(cid) for cid in batch),
                "beginDate": date_from.isoformat(),
                "endDate": date_to.isoformat(),
            }
            payload = await self._request("GET", "/adv/v3/fullstats", params=params)
            # WB returns null (decoded as None) when no campaign in the batch
            # had activity in the window — a legitimately empty result.
            if payload is None:
                continue
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected fullstats response shape (expected a top-level "
                    f"list, got {type(payload).__name__})."
                )
            results.extend(WBAdvCampaignStats.model_validate(rec) for rec in payload if rec)
        return results

    async def list_campaigns(self) -> list[WBCampaign]:
        """List every advertising campaign with its type and status.

        Endpoint: ``GET /adv/v1/promotion/count`` (no params). WB groups
        campaigns by ``(type, status)``; this flattens the groups into one
        descriptor per campaign id. Campaign names are not available here.

        Returns:
            A flat list of :class:`WBCampaign` descriptors.
        """
        payload = await self._request("GET", "/adv/v1/promotion/count")
        if not isinstance(payload, dict):
            raise IntegrationError(
                "Unexpected promotion/count response shape (expected an object, "
                f"got {type(payload).__name__})."
            )
        # "adverts" is null when the account has no campaigns — legitimate.
        raw_groups = payload.get("adverts")
        groups = [WBCampaignGroup.model_validate(g) for g in raw_groups or []]
        return [
            WBCampaign(campaign_id=ref.advert_id, type=group.type, status=group.status)
            for group in groups
            for ref in group.advert_list
        ]

    async def list_adverts(self) -> list[WBAdvertV2]:
        """List every campaign with its bid type and display-zone placements.

        Endpoint: ``GET /api/advert/v2/adverts`` (no params).

        Verified against the live WB API (2026-07): the response is
        ``{"adverts": [...]}`` with one descriptor per campaign carrying
        ``bid_type`` (``unified``/``manual``), a human-readable name, the
        payment model, and the ``placements`` zone toggles the monitoring
        matrix classifies campaigns by.

        Returns:
            One :class:`WBAdvertV2` per campaign on the account.
        """
        payload = await self._request("GET", "/api/advert/v2/adverts")
        if not isinstance(payload, dict):
            raise IntegrationError(
                "Unexpected adverts-v2 response shape (expected an object, "
                f"got {type(payload).__name__})."
            )
        # "adverts" is null when the account has no campaigns — legitimate.
        return [WBAdvertV2.model_validate(a) for a in payload.get("adverts") or []]

    #: Max (campaign, SKU) pairs per normquery-stats request (WB caps ``items``).
    _NORMQUERY_BATCH = 100

    async def fetch_campaign_budget(self, campaign_id: int) -> int:
        """Return one campaign's remaining budget, in the account's currency.

        Endpoint: ``GET /adv/v1/budget?id=<advertId>`` → ``{"cash", "netting",
        "total", "currency"}``. ``total`` is the whole remaining budget and the
        only field worth reading; ``cash``/``netting`` split it by funding
        source and were 0/0 on every campaign sampled.

        **A zero here is trustworthy, and that took checking.** Every campaign
        this account has finished (status 7) answers ``total: 0`` with an empty
        ``currency`` — which on its own is indistinguishable from an endpoint
        that simply does not work for our campaign types. Measured live
        2026-09-07 across statuses: running campaigns (status 9) answered 3818,
        3504 and 14929 KGS, and a paused one (11) answered 350. So the endpoint
        reports real numbers and ``0`` means the budget is spent, which is what
        lets the A/Б rotation stop on it.

        Args:
            campaign_id: WB advert id.

        Returns:
            Remaining budget. Rounded to whole units — WB reports it that way.

        Raises:
            IntegrationError: If the response is not the documented shape. NOT
                raised for a zero: that is an answer, not a failure.
        """
        payload = await self._request("GET", "/adv/v1/budget", params={"id": campaign_id})
        if not isinstance(payload, dict) or "total" not in payload:
            raise IntegrationError(
                "Unexpected adv/v1/budget response shape (expected an object with 'total')."
            )
        return int(payload["total"])

    async def fetch_search_zone_stats(
        self,
        *,
        pairs: list[tuple[int, int]],
        date_from: date,
        date_to: date,
    ) -> list[WBNormQueryItem]:
        """Fetch daily SEARCH-zone advertising stats per (campaign, SKU) pair.

        Endpoint: ``POST /adv/v1/normquery/stats``.

        Verified against the live WB API (2026-07): the body is ``{"from", "to",
        "items": [{"advertId", "nmId"}, ...]}`` with at most
        :attr:`_NORMQUERY_BATCH` items per request (transparently chunked here);
        the limiter allows ~10 requests/min. Each response item carries one
        ``dailyStats`` entry per day x search cluster; summing clusters per day
        yields the campaign's search-zone slice, which the analytics layer
        subtracts from fullstats totals to derive the recommendations («полки»)
        zone for unified-bid campaigns.

        Args:
            pairs: ``(campaign_id, nm_id)`` pairs to request.
            date_from: Inclusive period start (Moscow time).
            date_to: Inclusive period end (Moscow time).

        Returns:
            One :class:`WBNormQueryItem` per pair that returned data.
        """
        results: list[WBNormQueryItem] = []
        for offset in range(0, len(pairs), self._NORMQUERY_BATCH):
            batch = pairs[offset : offset + self._NORMQUERY_BATCH]
            body: dict[str, object] = {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "items": [{"advertId": campaign_id, "nmId": nm_id} for campaign_id, nm_id in batch],
            }
            payload = await self._request("POST", "/adv/v1/normquery/stats", json_body=body)
            if payload is None:
                continue
            if not isinstance(payload, dict):
                raise IntegrationError(
                    "Unexpected normquery-stats response shape (expected an object, "
                    f"got {type(payload).__name__})."
                )
            # "items" is null when no pair had search traffic — legitimate.
            results.extend(WBNormQueryItem.model_validate(i) for i in payload.get("items") or [])
        return results
