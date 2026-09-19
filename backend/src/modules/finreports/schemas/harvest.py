"""DTOs for the manual «Обновить» trigger and its status poll.

The poll carries the P&L's freshness line as well as the button's spinner: the
same two facts answer "has the run finished?" and "why does the statement stop
where it does?", and serving them together is what keeps every poll refreshing
the line for free.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class LatestReportOut(BaseModel):
    """The newest WB report on file — what we hold, and when we pulled it."""

    report_id: int = Field(description="WB realizationreport_id.")
    date_from: date | None = Field(
        default=None,
        description=(
            "Start of the period WB states the report covers. Null on the "
            "occasional header WB serves with no stated period."
        ),
    )
    date_to: date | None = Field(
        default=None, description="End of the stated period; null for the same reason."
    )
    harvested_at: datetime = Field(
        description="When this header was ingested (UTC instant, not a calendar day)."
    )


class FreshnessCheckOut(BaseModel):
    """What the hourly gate found the last time it asked WB for something newer."""

    outcome: Literal[
        "never_harvested",
        "up_to_date",
        "wb_empty",
        "wb_has_new",
        "probe_failed",
        "rate_blocked",
    ] = Field(
        description=(
            "'wb_empty' is the only one that means «нового ничего нет». "
            "'probe_failed' means WB did not answer — an unanswered question, "
            "never to be rendered as reassurance. 'rate_blocked' means WB has "
            "the endpoint shut and we did not ask: also not reassurance, and "
            "the one case where waiting is genuinely the only option."
        )
    )
    checked_at: datetime = Field(
        description=(
            "When the verdict was reached (UTC instant). Staleness is the "
            "signal: a confident 'nothing new' from six hours ago is what a "
            "dead harvester looks like."
        )
    )
    probe_from: date | None = Field(
        default=None,
        description="Start of the settlement window asked about; null when no request was made.",
    )
    probe_to: date | None = Field(default=None, description="End of that window.")


class HarvestStateResponse(BaseModel):
    """Whether a harvest is running, how far the history reaches, and how fresh it is."""

    running: bool = Field(
        description=(
            "True while a harvest (scheduled or manual) holds the lock. Advisory: "
            "it can change between this answer and any action taken on it."
        )
    )
    latest_settled: date | None = Field(
        default=None,
        description=(
            "Last settlement day this workspace's harvested reports cover. "
            "Unchanged after a finished run means WB had nothing new — which is "
            "a success, not a failure."
        ),
    )
    latest_report: LatestReportOut | None = Field(
        default=None,
        description="The newest report on file, or null for a never-harvested workspace.",
    )
    last_check: FreshnessCheckOut | None = Field(
        default=None,
        description=(
            "The last recorded freshness verdict, or null when there is none — "
            "never checked, expired, or an unreadable record. All three mean "
            "«мы не проверяли», which is the honest answer."
        ),
    )


class HarvestTriggerResponse(BaseModel):
    """Outcome of pressing «Обновить» — always an answer, never a wait."""

    status: Literal["started", "already_running", "rate_limited"] = Field(
        description=(
            "'started' — a harvest was enqueued; 'already_running' — one was "
            "already in flight and nothing was enqueued; 'rate_limited' — WB "
            "would not accept a settlement request yet, so nothing was "
            "enqueued and the caller is told when to come back."
        )
    )
    task_id: str | None = Field(
        default=None,
        description="Celery id of the enqueued harvest, absent when none was enqueued.",
    )
    retry_after_seconds: int | None = Field(
        default=None,
        description=(
            "Only on 'rate_limited': seconds until WB's settlement endpoint "
            "would accept a request. Read from the shared rate bucket, so it "
            "costs no WB request to produce."
        ),
    )


__all__ = [
    "FreshnessCheckOut",
    "HarvestStateResponse",
    "HarvestTriggerResponse",
    "LatestReportOut",
]
