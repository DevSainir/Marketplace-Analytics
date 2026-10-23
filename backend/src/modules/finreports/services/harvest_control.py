"""Read side of the manual "Refresh" trigger, and of the P&L's freshness line.

The hourly schedule closes most of the gap between WB publishing a report and
the P&L showing it, but not all of it: a report published at 02:00 waits for the
08:00 tick, and a worker that was down for its tick waits for the next one. When
the seller can see on WB's own site that a report exists, they need a way to say
"fetch it now" instead of waiting for a clock.

Since the freshness line was added, the same answer serves a second question the
page has to answer on every load: *why does the statement stop where it does?*
That takes two facts, and neither works without the other — **what we hold**
(the newest report on file, and when we pulled it) and **when we last asked**
(what the hourly gate found, and the moment it found it). "No new reports"
means nothing without "and we asked 12 minutes ago": a confident "nothing new"
that is six hours stale is a dead harvester wearing the same words.

Two things this service does NOT do. It does not decide whether the harvest may
run — the task owns that, under the same lock the scheduled run takes
(:func:`src.modules.finreports.tasks.harvest.harvest_all_workspaces`); this only
*reports* the lock, so the button can say "already running" instead of silently
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
from src.core.timeutils import moscow_today
from src.integrations.wildberries.endpoints import SALES_REPORTS_DETAILED_PATH
from src.integrations.wildberries.rate_limit import finance_reports_rate_gate
from src.modules.finreports.constants import HARVEST_LOCK_KEY, SETTLEMENT_BLOCK_THRESHOLD_SECONDS
from src.modules.finreports.repos import (
    DailySettlementRepository,
    FinancialReportRepository,
    LatestReportHeader,
    SettlementUploadRepository,
)
from src.modules.finreports.services.freshness_record import (
    FreshnessRecordStore,
    FreshnessVerdict,
)
from src.modules.finreports.services.settlement_calendar import next_formed_period
from src.modules.workspaces.contract import WorkspaceTokenBundle


@dataclass(frozen=True)
class HarvestState:
    """What the "Refresh" button and the freshness line need to know."""

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
    #: Newest day the PROVISIONAL daily tail covers, when it reaches past the
    #: settled weekly period — otherwise ``None``.
    #:
    #: Deliberately a second field rather than a larger :attr:`latest_settled`.
    #: The statement now shows figures for days no weekly report covers yet, and
    #: a page that showed them under "Latest WB report: 14-20 Sep" would be
    #: contradicting itself; one that folded them INTO that date would be
    #: claiming a settlement document WB has not issued. The two claims are
    #: different and are reported as two.
    provisional_through: date | None = None
    #: The weekly period after the newest one we hold, once WB's calendar says
    #: its report is formed — ``(date_from, date_to)`` — otherwise ``None``.
    #:
    #: WB shows a report on its own site hours before the API lists it (12.10.2026:
    #: on the site by 08:00, absent from ``sales-reports/list`` at 08:05). A seller
    #: looking at both sees «WB has it, we don't» and reads a broken harvest; this
    #: is what lets the page say "formed, waiting for the API" instead. Derived from the
    #: calendar, never from a WB request — see :mod:`.settlement_calendar`.
    awaited_period: tuple[date, date] | None = None
    #: The newest hand-uploaded report standing in the statement, if any —
    #: ``(date_from, date_to)``. Its rows are WB's own document, but not yet
    #: checked against the API's, and the page says so.
    uploaded_period: tuple[date, date] | None = None


class HarvestControlService:
    """Reports harvest liveness, coverage and freshness for one workspace."""

    def __init__(
        self,
        *,
        report_repo: FinancialReportRepository,
        daily_repo: DailySettlementRepository,
        redis: Redis,
        freshness_records: FreshnessRecordStore,
        load_tokens: Callable[[uuid.UUID], Awaitable[WorkspaceTokenBundle | None]],
        upload_repo: SettlementUploadRepository | None = None,
    ) -> None:
        """Wire the service to its sources.

        Args:
            report_repo: Source of the newest harvested report header.
            daily_repo: Source of how far the provisional daily tail reaches.
            redis: The client holding the harvest lock.
            freshness_records: Where the harvest task records what it found.
            load_tokens: Resolves a workspace's WB credentials. Only the
                "Finance" token is used, and only to name the rate bucket —
                see :meth:`settlement_retry_after`.
            upload_repo: Source of the hand-uploaded report standing in, if any.
        """
        self._report_repo = report_repo
        self._daily_repo = daily_repo
        self._redis = redis
        self._freshness_records = freshness_records
        self._load_tokens = load_tokens
        self._uploads = upload_repo

    async def settlement_retry_after(self, *, workspace_id: uuid.UUID) -> float:
        """Seconds before WB would accept a settlement request for this workspace.

        A click shortly after a tick used to enqueue a harvest whose first act
        was to sit still waiting for WB's next token — seven minutes of
        "Refreshing…" with nothing happening (observed 2026-09-09). The bucket
        already knows the number, and it is in shared Redis, so the answer costs
        a Redis round trip and **no WB request**: asking WB whether WB will
        accept a request is the one thing that cannot be done here.

        **It has to be the bucket the harvest actually spends.** This read the
        statistics gate on ``reportDetailByPeriod`` until 2026-09-23, which is
        the endpoint the harvest left on 22.09 — a bucket nothing writes to any
        more, so it always answered «open» and the button's `rate_limited`
        branch became unreachable. A seller clicking into a standing block was
        told the harvest had started, and then watched it not happen.

        Read-only in every sense — it takes no token from the bucket, so the
        page may ask as often as it likes without spending the harvest's budget.

        Args:
            workspace_id: Whose bucket to inspect. The bucket is per seller
                token, so one tenant's block says nothing about another's.

        **A refill is not a wait worth refusing.** The same threshold as the
        fleet tick (``SETTLEMENT_BLOCK_THRESHOLD_SECONDS``): up to a minute after
        the backfill or the daily tail took a token, the harvest's own gate
        queues through it, so the button starts the harvest rather than telling
        the seller to come back.

        Returns:
            Seconds to wait when WB has shut the method, or ``0.0`` otherwise —
            including an ordinary refill, no "Finance" token, or a bucket that
            cannot be read. Fails open: an unknown block is not a block.
        """
        tokens = await self._load_tokens(workspace_id)
        if tokens is None or not tokens.finance:
            return 0.0
        gate = finance_reports_rate_gate(settings, token=tokens.finance)
        shut_for = await gate.retry_after(SALES_REPORTS_DETAILED_PATH)
        return shut_for if shut_for > SETTLEMENT_BLOCK_THRESHOLD_SECONDS else 0.0

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
        settled = latest.date_to if latest else None
        # Reported only when it actually reaches further than the settled
        # history. Once the weekly report covering those days lands, the tail is
        # behind it and saying so would be noise — the same day, announced twice.
        tail = await self._daily_repo.covered_through(workspace_id=workspace_id)
        standing = await self._uploads.standing(workspace_id=workspace_id) if self._uploads else []
        uploaded = next(
            ((u.date_from, u.date_to) for u in standing if u.date_from and u.date_to), None
        )
        return HarvestState(
            running=await is_held(HARVEST_LOCK_KEY, redis=self._redis),
            latest_settled=settled,
            latest_report=latest,
            last_check=await self._freshness_records.get(workspace_id),
            provisional_through=tail if tail and (settled is None or tail > settled) else None,
            awaited_period=(
                next_formed_period(after=settled, today=moscow_today()) if settled else None
            ),
            uploaded_period=uploaded,
        )


__all__ = ["HarvestControlService", "HarvestState"]
