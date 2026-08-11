"""DTOs for the manual «Обновить» trigger and its status poll."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class HarvestStateResponse(BaseModel):
    """Whether a harvest is running, and how far the harvested history reaches."""

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


class HarvestTriggerResponse(BaseModel):
    """Outcome of pressing «Обновить»."""

    status: Literal["started", "already_running"] = Field(
        description=(
            "'started' — a harvest was enqueued; 'already_running' — one was "
            "already in flight and nothing was enqueued."
        )
    )
    task_id: str | None = Field(
        default=None,
        description="Celery id of the enqueued harvest, absent when none was enqueued.",
    )


__all__ = ["HarvestStateResponse", "HarvestTriggerResponse"]
