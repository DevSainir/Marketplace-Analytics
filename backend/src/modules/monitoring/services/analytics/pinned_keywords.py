"""Pinned-phrase service — «Закрепить» and the cards it produces.

A service of its own rather than more methods on
:class:`~src.modules.monitoring.services.analytics.clusters.ClusterAnalytics`,
for the reason that split the panel in the first place: this half is pure CRUD
over one small table and answers instantly, while the probe half walks a
rate-limited public host. Keeping them apart is what stops a throttled WB from
being able to break «показать закреплённые».

The probing itself is NOT here. A pin's number is written by the scheduled task
(:mod:`src.modules.monitoring.tasks.positions`), so this module never makes an
outbound call — it reads what the last run stored and hands it to the page.
"""

from __future__ import annotations

import uuid

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.monitoring.models.pinned_keywords import KEYWORD_MAX_LENGTH, PinnedKeyword
from src.modules.monitoring.repos import PinnedKeywordRepository
from src.modules.monitoring.schemas.clusters import PinnedKeywordItem, PinnedKeywordsResponse


def clean_keyword(raw: str) -> str:
    """Normalize a typed phrase into the form a pin is keyed by.

    Whitespace-collapsed and casefolded so «Носки  Мужские» and «носки мужские»
    are one pin rather than two cards showing the same number: WB normalizes the
    phrase itself before ranking, so treating them as distinct would spend the
    rate budget twice for one answer.

    Args:
        raw: The phrase as typed.

    Returns:
        The cleaned phrase.

    Raises:
        ValidationError: When the phrase is blank or longer than the probe
            accepts (a pin that can never be checked is not worth storing).
    """
    collapsed = " ".join(raw.split()).casefold()
    if not collapsed:
        raise ValidationError("Запрос не может быть пустым.")
    if len(collapsed) > KEYWORD_MAX_LENGTH:
        raise ValidationError(
            f"Запрос длиннее {KEYWORD_MAX_LENGTH} символов — WB не ищет по таким фразам."
        )
    return collapsed


class PinnedKeywordService:
    """Lists, pins and unpins the phrases a SKU's position is watched for."""

    def __init__(self, *, pinned_keyword_repo: PinnedKeywordRepository) -> None:
        """Bind the service to its repository.

        Args:
            pinned_keyword_repo: Sole owner of ``monitoring.pinned_keyword`` SQL.
        """
        self._pins = pinned_keyword_repo

    async def list_for_sku(self, *, nm_id: int) -> PinnedKeywordsResponse:
        """Return one SKU's pinned phrases with their last known positions.

        Args:
            nm_id: The SKU (ownership already proven by the route's guard).

        Returns:
            The pins in pin order.
        """
        rows = await self._pins.list_for_sku(nm_id=nm_id)
        return PinnedKeywordsResponse(nm_id=nm_id, items=[_to_item(row) for row in rows])

    async def pin(self, *, nm_id: int, keyword: str) -> PinnedKeywordItem:
        """Pin a phrase to a SKU.

        Idempotent: pinning an already-pinned phrase returns the existing card
        with its stored number intact, rather than blanking what the seller is
        watching.

        Args:
            nm_id: The SKU to pin to.
            keyword: The phrase as typed.

        Returns:
            The pinned card.

        Raises:
            ValidationError: On a blank or over-long phrase.
        """
        row = await self._pins.pin(nm_id=nm_id, keyword=clean_keyword(keyword))
        return _to_item(row)

    async def unpin(self, *, nm_id: int, keyword: str) -> None:
        """Remove a pin.

        Args:
            nm_id: The SKU the phrase is pinned to.
            keyword: The phrase to unpin.

        Raises:
            NotFoundError: When the phrase was not pinned to this SKU — the UI
                and the stored list disagree, and silently succeeding would hide
                that from a seller who just watched a card refuse to disappear.
            ValidationError: On a blank or over-long phrase.
        """
        deleted = await self._pins.unpin(nm_id=nm_id, keyword=clean_keyword(keyword))
        if not deleted:
            raise NotFoundError("Такой запрос не закреплён за этим артикулом.")

    async def count_for_workspace(self, *, workspace_id: uuid.UUID) -> int:
        """Count the workspace's pins — how much work «Проверить все позиции» queues.

        Args:
            workspace_id: The active workspace.

        Returns:
            The number of pinned phrases across the workspace's catalogue.
        """
        return len(await self._pins.list_for_workspace(workspace_id=workspace_id))


def _to_item(row: PinnedKeyword) -> PinnedKeywordItem:
    """Map a stored pin onto its wire shape.

    Args:
        row: The ORM row (never leaves this layer).

    Returns:
        The DTO the page renders.
    """
    return PinnedKeywordItem(
        keyword=row.keyword,
        normalized_query=row.normalized_query or None,
        position=row.last_position,
        positions_scanned=row.last_positions_scanned,
        total_found=row.last_total_found,
        truncated=row.last_truncated,
        checked_at=row.last_checked_at,
        created_at=row.created_at,
    )
