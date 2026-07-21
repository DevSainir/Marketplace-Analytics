"""Per-day SKU annotations: the «Комментарий» notes and the «Действия» answers."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.repos import SkuDayActionRepository, SkuDayCommentRepository
from src.modules.monitoring.schemas import (
    DayActionResponse,
    DayActionState,
    DayCommentResponse,
    DayNote,
)


class DayAnnotationAnalytics:
    """Saves and clears the per-(SKU, day) notes and action answers."""

    def __init__(
        self,
        *,
        day_comment_repo: SkuDayCommentRepository,
        day_action_repo: SkuDayActionRepository,
    ) -> None:
        """Inject the note and action stores."""
        self._day_comments = day_comment_repo
        self._day_actions = day_action_repo

    async def set_day_note(
        self,
        *,
        nm_id: int,
        comment_date: date,
        body: str | None = None,
        header: str | None = None,
    ) -> DayCommentResponse:
        """Save one SKU-day's note — the comment, the header, or both.

        A field left as ``None`` keeps its stored value, so the two inputs save
        independently. Values are stripped; emptying BOTH deletes the day's
        row. Notes are global — shared by every account, keyed by
        ``(nm_id, comment_date)``.

        Nothing here carries the header onto later days: that happens once at
        the day boundary (``monitoring.carry_day_headers``), which copies it as
        a real row. So editing or clearing a header only ever changes its own
        day — later days keep whatever was carried onto them.

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day the note describes.
            body: New comment text, or ``None`` to leave it unchanged.
            header: New header text, or ``None`` to leave it unchanged.

        Returns:
            The stored note (``note`` is ``None`` after a full clear).
        """
        current = await self._day_comments.get(nm_id=nm_id, comment_date=comment_date)
        new_body = (body if body is not None else (current.body if current else "")).strip()
        new_header = (header if header is not None else (current.header if current else "")).strip()

        if not new_body and not new_header:
            await self._day_comments.clear(nm_id=nm_id, comment_date=comment_date)
            return DayCommentResponse(nm_id=nm_id, comment_date=comment_date, note=None)

        await self._day_comments.set(
            nm_id=nm_id, comment_date=comment_date, body=new_body, header=new_header
        )
        return DayCommentResponse(
            nm_id=nm_id,
            comment_date=comment_date,
            note=DayNote(body=new_body, header=new_header),
        )

    async def carry_day_headers(self, *, source_day: date, target_day: date) -> int:
        """Copy every SKU's ``source_day`` header onto ``target_day``.

        The day-boundary carry behind the running title in the matrix's notes
        row (see :meth:`set_day_note`). Idempotent: a day that already has a
        header keeps it.

        Args:
            source_day: The day to copy headers from (the previous day).
            target_day: The day to copy them onto (the new day).

        Returns:
            The number of headers carried.
        """
        return await self._day_comments.carry_headers_to_day(
            source_day=source_day, target_day=target_day
        )

    async def set_day_action(
        self, *, nm_id: int, action_date: date, action: DayActionState
    ) -> DayActionResponse:
        """Save one SKU-day's action row (full state, last write wins).

        The frontend PUTs the WHOLE day state on every change (same convention
        as the comment note). A state with every answer cleared deletes the
        day's row instead of storing an all-``NULL`` one. Actions are global —
        shared by every account, keyed by ``(nm_id, action_date)``.

        Args:
            nm_id: WB SKU identifier.
            action_date: The day the actions describe.
            action: The full desired state of the day's answers.

        Returns:
            The stored state (``action`` is ``None`` after a full clear).
        """
        if action.is_empty():
            await self._day_actions.clear(nm_id=nm_id, action_date=action_date)
            return DayActionResponse(nm_id=nm_id, action_date=action_date, action=None)
        await self._day_actions.set(
            nm_id=nm_id,
            action_date=action_date,
            uni_rk_enabled=action.uni_rk_enabled,
            uni_rk_budget=action.uni_rk_budget,
            manual_rk_enabled=action.manual_rk_enabled,
            manual_rk_budget=action.manual_rk_budget,
            price_change=action.price_change,
            price_change_amount=action.price_change_amount,
        )
        return DayActionResponse(nm_id=nm_id, action_date=action_date, action=action)
