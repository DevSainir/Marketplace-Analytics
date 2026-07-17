"""DTOs for the per-day comment note («Комментарий»)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

#: Upper bound on a comment's length (a note, not an essay). Enforced at the
#: presentation boundary so the service/repo never see oversized bodies.
COMMENT_MAX_LENGTH: int = 2000


class DayCommentResponse(BaseModel):
    """One SKU-day's comment. ``body`` is ``None`` when the day has no note."""

    nm_id: int = Field(description="WB SKU identifier.")
    comment_date: date = Field(description="The day the note describes.")
    body: str | None = Field(default=None, description="The note text, or null when empty.")


class CommentUpdateRequest(BaseModel):
    """Body of the comment endpoint: the desired note text.

    A blank/whitespace-only body clears the note (deletes the row).
    """

    body: str = Field(
        default="",
        max_length=COMMENT_MAX_LENGTH,
        description="The note text; blank clears the comment.",
    )
