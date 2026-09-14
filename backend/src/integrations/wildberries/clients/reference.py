"""One thin client for the WB surfaces we only CAPTURE, never interpret.

Every other client in this package models an endpoint family properly: typed
schemas, WB's quirks encoded, a table the rows land in. The feeds behind
:mod:`src.modules.guide` have none of that yet, on purpose — that module stores
WB's answer verbatim because nobody has decided what to ask of it. Giving each
of them a typed client now would mean inventing its shape twice: once here, and
again when a feed graduates into the module that actually uses it.

So this client is deliberately generic. It knows the two request SHAPES WB
serves reference data through — a plain GET, and the create/poll/download task
flow the heavier reports use — and nothing about any particular feed. Which path
and which parameters lives in :mod:`src.modules.guide.services.fetch`, beside
the cadence and the retention that justify it.

It is still a real WB client: it inherits the retry ladder, the
``Retry-After`` handling, the metrics and the rate gate from
:class:`~src.integrations.wildberries.clients.base.BaseWBClient`. The gate
matters more here than anywhere else, because this traffic must never cost a
harvest that earns money — see the caller for which gate each host gets.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import RateGate


class WBReferenceClient(BaseWBClient):
    """A host, a token and a gate — for feeds captured as-is."""

    WB_SURFACE = "reference"

    #: Status-poll cadence and ceiling for the async report flow. Sized from
    #: live probes on 2026-09-12: every acceptance/paid-storage report asked for
    #: was ``done`` on the first poll, so this ceiling is for a bad day rather
    #: than the normal one.
    _POLL_INTERVAL_SECONDS = 6.0
    _POLL_MAX_ATTEMPTS = 20

    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str,
        token: str,
        rate_gate: RateGate | None = None,
    ) -> None:
        """Build a capture client for one WB host.

        Args:
            settings: Transport configuration (timeouts, retry ladder).
            base_url: The WB host, resolved by the caller from settings so this
                class stays ignorant of which surface it is talking to.
            token: Bearer token for that host's scope.
            rate_gate: Pacing gate. Passed by the caller because the right
                bucket depends on the surface, and on this path the answer is
                sometimes "the same bucket a paying harvest uses" — which is
                exactly the case that must not be got wrong.
        """
        super().__init__(
            base_url=base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            rate_gate=rate_gate,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one path and return the decoded body.

        Args:
            path: Request path on this client's host.
            params: Query parameters, already in WB's own casing.

        Returns:
            Whatever WB answered — a list, an object, or ``None`` for the
            ``204 No Content`` several of these feeds use for "empty window".
            Deliberately untyped: the caller stores it rather than reading it.
        """
        return await self._request("GET", path, params=params)

    async def run_report(self, path: str, params: dict[str, Any]) -> Any:
        """Drive WB's async report flow: create, poll until done, download.

        Three of WB's heavier reports work this way. The shape is identical
        across them — ``{"data": {"taskId": ...}}``, then
        ``{"data": {"status": "done"}}``, then the rows — so it lives here
        rather than being written out per feed.

        Args:
            path: The report's base path, e.g. ``/api/v1/acceptance_report``.
            params: Window parameters for the create call.

        Returns:
            The downloaded rows, or ``None`` when WB answers the download with
            ``204`` (an empty window, which is not an error).

        Raises:
            IntegrationError: When the create call returns no task id, or the
                report is still not ready after the poll ceiling.
        """
        created = await self._request("GET", path, params=params)
        task_id = ""
        if isinstance(created, dict):
            data = created.get("data")
            if isinstance(data, dict):
                task_id = str(data.get("taskId") or "")
        if not task_id:
            raise IntegrationError(f"WB {path} returned no taskId for the report window.")

        for _ in range(self._POLL_MAX_ATTEMPTS):
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)
            status = await self._request("GET", f"{path}/tasks/{task_id}/status")
            state = ""
            if isinstance(status, dict):
                data = status.get("data")
                if isinstance(data, dict):
                    state = str(data.get("status") or "")
            if state == "done":
                return await self._request("GET", f"{path}/tasks/{task_id}/download")
            if state in {"canceled", "purged"}:
                raise IntegrationError(f"WB {path} report {task_id} ended as '{state}'.")
        raise IntegrationError(
            f"WB {path} report {task_id} was still not ready after {self._POLL_MAX_ATTEMPTS} polls."
        )


__all__ = ["WBReferenceClient"]
