"""Read side of the manual «Обновить» trigger, and of the P&L's freshness line.

The hourly schedule closes most of the gap between WB publishing a report and
the P&L showing it, but not all of it: a report published at 02:00 waits for the
08:00 tick, and a worker that was down for its tick waits for the next one. When
the seller can see on WB's own site that a report exists, they need a way to say
"fetch it now" instead of waiting for a clock.

Since the freshness line was added, the same answer serves a second question the
page has to answer on every load: *why does the statement stop where it does?*
That takes two facts, and neither works without the other — **what we hold**
(the newest report on file, and when we pulled it) and **when we last asked**
(what the hourly gate found, and the moment it found it). «Новых отчётов нет»
means nothing without «и мы спросили 12 минут назад»: a confident "nothing new"
that is six hours stale is a dead harvester wearing the same words.

Two things this service does NOT do. It does not decide whether the harvest may
run — the task owns that, under the same lock the scheduled run takes
(:func:`src.modules.finreports.tasks.harvest.harvest_all_workspaces`); this only
*reports* the lock, so the button can say «уже выполняется» instead of silently
queueing a run that will no-op. And **it never probes WB itself.** The freshness
answer is relayed from what the task recorded, nothing more: a page load may not
spend the WB request budget the hourly schedule is metered against, and a page
that probed on every open would be the most expensive surface in the product.

Every answer here is a snapshot that can be stale by the time it is read, and
nothing downstream may treat it as a guarantee.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from redis.asyncio import Redis

from src.core.config import settings
from src.core.locks import is_held
from src.integrations.wildberries.endpoints import SETTLEMENT_REPORT_PATH
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.modules.finreports.constants import HARVEST_LOCK_KEY
from src.modules.finreports.repos import FinancialReportRepository, LatestReportHeader
from src.modules.finreports.services.freshness_record import (
    FreshnessRecordStore,
    FreshnessVerdict,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle


@dataclass(frozen=True)
class HarvestState:
    """What the «Обновить» button and the freshness line need to know."""

    #: Whether a harvest (scheduled or manual) currently holds the lock.
    running: bool
    #: Last settlement day this workspace's harvested reports cover, if any.
    #: The frontend compares it across a run to tell "pulled a new report" from
    #: "asked WB and there was nothing new" — both are successful outcomes and
    #: only this distinguishes them.
    #:
    #: Derived from :attr:`latest_report` rather than queried separately, so the
    #: two halves of the answer cannot disagree about which week is the newest.
    latest_settled: date | None
    #: The newest report on file, or ``None`` for a never-harvested workspace.
    latest_report: LatestReportHeader | None = None
    #: What the hourly gate found the last time it asked, or ``None`` when
    #: nothing is recorded — never checked, expired, or a record that came back
    #: corrupt. All three read as "we have not checked", which is the honest
    #: answer and the one the page is built to show.
    last_check: FreshnessVerdict | None = None


class HarvestControlService:
    """Reports harvest liveness, coverage and freshness for one workspace."""

    def __init__(
        self,
        *,
        report_repo: FinancialReportRepository,
        redis: Redis,
        freshness_records: FreshnessRecordStore,
        load_tokens: Callable[[uuid.UUID], Awaitable[WorkspaceTokenBundle | None]],
    ) -> None:
        """Wire the service to its sources.

        Args:
            report_repo: Source of the newest harvested report header.
            redis: The client holding the harvest lock.
            freshness_records: Where the harvest task records what it found.
            load_tokens: Resolves a workspace's WB credentials. Only the
                statistics token is used, and only to name the rate bucket —
                see :meth:`settlement_retry_after`.
        """
        self._report_repo = report_repo
        self._redis = redis
        self._freshness_records = freshness_records
        self._load_tokens = load_tokens

    async def settlement_retry_after(self, *, workspace_id: uuid.UUID) -> float:
        """Seconds before WB would accept a settlement request for this workspace.

        WB meters ``reportDetailByPeriod`` at one request per ~15 minutes, so a
        click shortly after the hourly tick used to enqueue a harvest whose
        first act was to sit still for most of a quarter of an hour — seven
        minutes of «Обновляем…» with nothing happening (prod 2026-09-09). The
        bucket already knows the number, and it is in shared Redis, so the
        answer costs a Redis round trip and **no WB request**: asking WB whether
        WB will accept a request is the one thing that cannot be done here.

        Read-only in every sense — it takes no token from the bucket, so the
        page may ask as often as it likes without spending the harvest's budget.

        Args:
            workspace_id: Whose bucket to inspect. The bucket is per seller
                token, so one tenant's block says nothing about another's.

        Returns:
            Seconds to wait, or ``0.0`` when a request may go out now —
            including when the workspace has no statistics token or the bucket
            cannot be read. Fails open: an unknown block is not a block.
        """
        tokens = await self._load_tokens(workspace_id)
        if tokens is None or not tokens.statistics:
            return 0.0
        gate = statistics_rate_gate(settings, token=tokens.statistics)
        return await gate.retry_after(SETTLEMENT_REPORT_PATH)

    async def get_state(self, *, workspace_id: uuid.UUID) -> HarvestState:
        """Return liveness, coverage and the last freshness verdict.

        Args:
            workspace_id: Tenancy scope for everything but the lock, which is
                platform-wide.

        Returns:
            The current :class:`HarvestState`. The freshness half is best-effort
            — a Redis outage yields ``last_check=None`` rather than an error,
            because a footnote may not take down the statement it annotates.
        """
        latest = await self._report_repo.latest_report(workspace_id=workspace_id)
        return HarvestState(
            running=await is_held(HARVEST_LOCK_KEY, redis=self._redis),
            latest_settled=latest.date_to if latest else None,
            latest_report=latest,
            last_check=await self._freshness_records.get(workspace_id),
        )


__all__ = ["HarvestControlService", "HarvestState"]
