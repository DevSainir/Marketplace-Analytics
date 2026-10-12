"""DTOs for uploading WB's weekly report by hand and following what became of it."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SettlementUploadOut(BaseModel):
    """One uploaded weekly report file, and how it ended."""

    id: uuid.UUID = Field(description="Upload id, to poll its status by.")
    status: Literal[
        "queued",
        "processing",
        "written",
        "already_held",
        "diverged",
        "failed",
        "confirmed",
        "replaced_diverged",
    ] = Field(
        description=(
            "'queued'/'processing' while the worker reads it. 'written' — its rows "
            "stand in the P&L until WB's API serves the report; 'already_held' — we "
            "hold the same rows, nothing written; 'diverged' — we hold this period "
            "and it differs, nothing written; 'failed' — refused, see message. "
            "'confirmed'/'replaced_diverged' — the API has since served the report."
        )
    )
    message: str = Field(default="", description="What to tell the seller, in Russian.")
    report_id: int | None = Field(default=None, description="WB's report number.")
    date_from: date | None = Field(default=None, description="First day of the period.")
    date_to: date | None = Field(default=None, description="Last day of the period.")
    rows_total: int = Field(default=0, description="Data rows in the file.")
    rows_written: int = Field(default=0, description="Rows this upload put into the P&L.")


__all__ = ["SettlementUploadOut"]
