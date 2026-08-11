"""Read side of the manual «Обновить» trigger: is a harvest running, and how far
does the harvested history reach.

The hourly schedule closes most of the gap between WB publishing a report and
the P&L showing it, but not all of it: a report published at 02:00 waits for the
08:00 tick, and a worker that was down for its tick waits for the next one. When
the seller can see on WB's own site that a report exists, they need a way to say
"fetch it now" instead of waiting for a clock.

What this service does NOT do is decide whether the harvest may run — the task
itself owns that, under the same lock the scheduled run takes
(:func:`src.modules.finreports.tasks.harvest.harvest_all_workspaces`). This only
*reports* the lock, so the button can say «уже выполняется» instead of silently
queueing a run that will no-op. Every answer here is a snapshot that can be stale
by the time it is read, and nothing downstream may treat it as a guarantee.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from redis.asyncio import Redis

from src.core.locks import is_held
from src.modules.finreports.constants import HARVEST_LOCK_KEY
from src.modules.finreports.repos import FinancialReportRepository


@dataclass(frozen=True)
class HarvestState:
    """What the «Обновить» button needs to know before and after a click."""

    #: Whether a harvest (scheduled or manual) currently holds the lock.
    running: bool
    #: Last settlement day this workspace's harvested reports cover, if any.
    #: The frontend compares it across a run to tell "pulled a new report" from
    #: "asked WB and there was nothing new" — both are successful outcomes and
    #: only this distinguishes them.
    latest_settled: date | None


class HarvestControlService:
    """Reports harvest liveness and coverage for one workspace."""

    def __init__(self, *, report_repo: FinancialReportRepository, redis: Redis) -> None:
        """Wire the service to the report repository and the shared Redis.

        Args:
            report_repo: Source of the harvested settlement coverage.
            redis: The client holding the harvest lock.
        """
        self._report_repo = report_repo
        self._redis = redis

    async def get_state(self, *, workspace_id: uuid.UUID) -> HarvestState:
        """Return whether a harvest is in flight and how far the history reaches.

        Args:
            workspace_id: Tenancy scope for the coverage half of the answer.

        Returns:
            The current :class:`HarvestState`.
        """
        return HarvestState(
            running=await is_held(HARVEST_LOCK_KEY, redis=self._redis),
            latest_settled=await self._report_repo.latest_settled_date(workspace_id=workspace_id),
        )


__all__ = ["HarvestControlService", "HarvestState"]
