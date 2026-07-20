"""DTOs for the per-day note («Комментарий» + its header)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

#: Upper bound on a comment's length (a note, not an essay). Enforced at the
#: presentation boundary so the service/repo never see oversized bodies.
COMMENT_MAX_LENGTH: int = 2000

#: Upper bound on a header's length — it is a title for the day, one line.
HEADER_MAX_LENGTH: int = 200


class DayNote(BaseModel):
    """One day's stored note: the free-text comment and its header.

    The two are independent. ``body`` is purely per-day; ``header`` is copied
    onto each new day at the day boundary, as a real row, so editing it later
    changes that day alone.
    """

    body: str = Field(default="", description="The comment text ('' when absent).")
    header: str = Field(default="", description="The note's title ('' when absent).")


class DayCommentResponse(BaseModel):
    """One SKU-day's note after a save.

    ``note`` is ``None`` when the save emptied both fields and the day's row
    was deleted.
    """

    nm_id: int = Field(description="WB SKU identifier.")
    comment_date: date = Field(description="The day the note describes.")
    note: DayNote | None = Field(
        default=None, description="The stored note, or null after a full clear."
    )


class CommentUpdateRequest(BaseModel):
    """Body of the note endpoint: the field(s) the user just edited.

    Both fields are optional and mean "leave unchanged" when omitted, so the
    header and the comment save independently without either clobbering the
    other. Sending a field as blank clears it; clearing both deletes the day's
    row.
    """

    body: str | None = Field(
        default=None,
        max_length=COMMENT_MAX_LENGTH,
        description="New comment text; blank clears it, omitted leaves it as is.",
    )
    header: str | None = Field(
        default=None,
        max_length=HEADER_MAX_LENGTH,
        description="New header text; blank clears it, omitted leaves it as is.",
    )
