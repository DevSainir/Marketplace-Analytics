"""Persistence for the review history (see :mod:`...models.reviews`).

Every statement carries ``workspace_id`` in its WHERE. The tables are under
row-level security too, but the worker connects as their owner, so the policy
does not apply on this path — the WHERE is the control here, not a courtesy.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.core.upsert import upsert_rows
from src.integrations.wildberries.schemas import WBFeedback
from src.modules.monitoring.models import (
    RatingSnapshot,
    ReviewEvent,
    ReviewEventKind,
    ReviewState,
)


@dataclass(frozen=True, slots=True)
class KnownReview:
    """What the previous walks recorded about one review."""

    nm_id: int
    imt_id: int
    valuation: int
    child_review_id: str | None
    vanished_on: date | None
    excluded: bool | None


@dataclass(frozen=True, slots=True)
class EventDraft:
    """A :class:`ReviewEvent` before it has an id and a date."""

    review_id: str
    nm_id: int
    imt_id: int
    kind: ReviewEventKind
    old_valuation: int | None = None
    new_valuation: int | None = None
    detail: str = ""


class ReviewRepository:
    """Reads and writes ``review_state``, ``review_event`` and ``rating_snapshot``."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the caller's session; the caller owns the transaction."""
        self._session = session

    async def known(
        self, *, workspace_id: uuid.UUID, review_ids: Collection[str]
    ) -> dict[str, KnownReview]:
        """The recorded state of the given reviews, keyed by id.

        Args:
            workspace_id: The workspace.
            review_ids: One page's ids — bounded by the page size.

        Returns:
            Only the ids already on record; a new review is simply absent.
        """
        if not review_ids:
            return {}
        rows = await self._session.execute(
            select(
                ReviewState.review_id,
                ReviewState.nm_id,
                ReviewState.imt_id,
                ReviewState.valuation,
                ReviewState.child_review_id,
                ReviewState.vanished_on,
                ReviewState.excluded,
            ).where(
                ReviewState.workspace_id == workspace_id,
                ReviewState.review_id.in_(list(review_ids)),
            )
        )
        return {
            row.review_id: KnownReview(
                nm_id=row.nm_id,
                imt_id=row.imt_id,
                valuation=row.valuation,
                child_review_id=row.child_review_id,
                vanished_on=row.vanished_on,
                excluded=row.excluded,
            )
            for row in rows
        }

    async def record_seen(
        self, *, workspace_id: uuid.UUID, items: Sequence[WBFeedback], seen_on: date
    ) -> int:
        """Upsert one page of listed reviews as seen on ``seen_on``.

        ``first_seen_on`` is written on insert only; ``vanished_on`` is cleared
        because a listed review has, by definition, not vanished.

        Returns:
            Rows submitted.
        """
        rows = [
            {
                "workspace_id": workspace_id,
                "review_id": item.id,
                "nm_id": item.product.nm_id,
                "imt_id": item.product.imt_id,
                "valuation": item.valuation,
                "created_at": item.created_date,
                "parent_review_id": item.parent_feedback_id,
                "child_review_id": item.child_feedback_id,
                "first_seen_on": seen_on,
                "last_seen_on": seen_on,
            }
            for item in _last_per_id(items)
        ]
        return await upsert_rows(
            self._session,
            ReviewState,
            rows,
            conflict_columns=("workspace_id", "review_id"),
            update_columns=(
                "nm_id",
                "imt_id",
                "valuation",
                "created_at",
                "parent_review_id",
                "child_review_id",
                "last_seen_on",
            ),
            also_set={"vanished_on": None},
        )

    async def add_events(
        self, *, workspace_id: uuid.UUID, observed_on: date, drafts: Iterable[EventDraft]
    ) -> int:
        """Append events. Returns how many were written."""
        rows = [
            {
                "id": uuid7(),
                "workspace_id": workspace_id,
                "observed_on": observed_on,
                "review_id": draft.review_id,
                "nm_id": draft.nm_id,
                "imt_id": draft.imt_id,
                "kind": draft.kind.value,
                "old_valuation": draft.old_valuation,
                "new_valuation": draft.new_valuation,
                "detail": draft.detail[:256],
            }
            for draft in drafts
        ]
        if rows:
            await self._session.execute(pg_insert(ReviewEvent), rows)
        return len(rows)

    async def count_live(self, *, workspace_id: uuid.UUID) -> int:
        """Reviews on record that have not vanished."""
        result = await self._session.execute(
            select(func.count())
            .select_from(ReviewState)
            .where(ReviewState.workspace_id == workspace_id, ReviewState.vanished_on.is_(None))
        )
        return int(result.scalar_one())

    async def missing(self, *, workspace_id: uuid.UUID, walked_on: date) -> list[EventDraft]:
        """Live reviews the walk of ``walked_on`` did not list, as VANISHED drafts.

        Loaded rather than moved in one ``INSERT … SELECT`` because an event
        needs a UUIDv7, which only Python mints here; the caller bounds the
        count before asking (:func:`count_missing`).
        """
        rows = await self._session.execute(
            select(
                ReviewState.review_id,
                ReviewState.nm_id,
                ReviewState.imt_id,
                ReviewState.valuation,
            ).where(*_missing_filter(workspace_id, walked_on))
        )
        return [
            EventDraft(
                review_id=row.review_id,
                nm_id=row.nm_id,
                imt_id=row.imt_id,
                kind=ReviewEventKind.VANISHED,
                old_valuation=row.valuation,
            )
            for row in rows
        ]

    async def count_missing(self, *, workspace_id: uuid.UUID, walked_on: date) -> int:
        """How many live reviews the walk of ``walked_on`` did not list."""
        result = await self._session.execute(
            select(func.count())
            .select_from(ReviewState)
            .where(*_missing_filter(workspace_id, walked_on))
        )
        return int(result.scalar_one())

    async def mark_vanished(self, *, workspace_id: uuid.UUID, walked_on: date) -> None:
        """Record every review the walk of ``walked_on`` missed as vanished that day."""
        await self._session.execute(
            update(ReviewState)
            .where(*_missing_filter(workspace_id, walked_on))
            .values(vanished_on=walked_on)
        )

    async def imt_ids(self, *, workspace_id: uuid.UUID) -> list[int]:
        """Every card group this workspace's reviews were left on, ascending."""
        rows = await self._session.execute(
            select(ReviewState.imt_id)
            .where(ReviewState.workspace_id == workspace_id, ReviewState.imt_id > 0)
            .distinct()
            .order_by(ReviewState.imt_id)
        )
        return list(rows.scalars())

    async def has_snapshot(self, *, workspace_id: uuid.UUID, imt_id: int) -> bool:
        """Whether this card group has been snapshotted before, on any day."""
        result = await self._session.execute(
            select(RatingSnapshot.imt_id)
            .where(RatingSnapshot.workspace_id == workspace_id, RatingSnapshot.imt_id == imt_id)
            .limit(1)
        )
        return result.first() is not None

    async def seller_api_count(self, *, workspace_id: uuid.UUID, imt_id: int) -> int:
        """Live, unreplaced reviews of a card group not known to be excluded."""
        result = await self._session.execute(
            select(func.count())
            .select_from(ReviewState)
            .where(
                ReviewState.workspace_id == workspace_id,
                ReviewState.imt_id == imt_id,
                ReviewState.vanished_on.is_(None),
                ReviewState.child_review_id.is_(None),
                ReviewState.excluded.is_not(True),
            )
        )
        return int(result.scalar_one())

    async def add_snapshot(self, row: Mapping[str, Any]) -> bool:
        """Insert one day's snapshot; the day's first observation stands.

        Returns:
            Whether a row was written (``False`` when the day already had one).
        """
        result = await self._session.execute(
            pg_insert(RatingSnapshot)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["snapshot_date", "workspace_id", "imt_id"])
            .returning(RatingSnapshot.imt_id)
        )
        return result.first() is not None

    async def set_exclusions(
        self, *, workspace_id: uuid.UUID, exclusions: Mapping[str, tuple[bool, str]]
    ) -> None:
        """Record the storefront's exclusion flag for the reviews it listed."""
        for review_id, (excluded, reasons) in exclusions.items():
            await self._session.execute(
                update(ReviewState)
                .where(
                    ReviewState.workspace_id == workspace_id,
                    ReviewState.review_id == review_id,
                )
                .values(excluded=excluded, excluded_reasons=reasons[:256])
            )


def _missing_filter(workspace_id: uuid.UUID, walked_on: date) -> tuple[Any, ...]:
    """Live reviews of the workspace last listed before the walk of ``walked_on``."""
    return (
        ReviewState.workspace_id == workspace_id,
        ReviewState.vanished_on.is_(None),
        ReviewState.last_seen_on < walked_on,
    )


def _last_per_id(items: Sequence[WBFeedback]) -> list[WBFeedback]:
    """One item per review id, the later winning — pages overlap on purpose."""
    return list({item.id: item for item in items}.values())


__all__ = ["EventDraft", "KnownReview", "ReviewRepository"]
