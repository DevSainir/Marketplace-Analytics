"""The heatmap's hand-set norms: what «Норма: ручной ввод» paints an article against.

One number per article per metric, shared by everyone in the workspace. The page
reads them all at once — at most every card times every metric — and paints;
nothing here touches the grid, which stays the same whichever norm is on.

An article is proved to be the workspace's own before its norm is written, for the
reason «Группы» are: WB article numbers are global, and a row for a stranger's
card would sit in this workspace's table for good.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationError
from src.modules.heatmap.repos import SkuNormRepository
from src.modules.heatmap.schemas import MetricKey, SkuNormList, SkuNormRead
from src.modules.monitoring.contract import load_workspace_catalog


class SkuNormService:
    """Lists, sets and clears one workspace's norms."""

    def __init__(self, repo: SkuNormRepository) -> None:
        """Wire the service from its repository."""
        self._repo = repo

    async def list_norms(self, *, workspace_id: uuid.UUID) -> SkuNormList:
        """Every norm of the workspace."""
        return SkuNormList(
            items=[
                SkuNormRead.model_validate({"nm_id": nm_id, "metric": metric, "value": value})
                for nm_id, metric, value in await self._repo.list_norms(workspace_id)
            ]
        )

    async def set_norm(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        nm_id: int,
        metric: MetricKey,
        value: float,
    ) -> SkuNormRead:
        """Set an article's norm on one metric, replacing the previous one.

        Raises:
            ValidationError: The article is not in the workspace's catalogue.
        """
        cards = await load_workspace_catalog(session, workspace_id=workspace_id)
        if nm_id not in {card.nm_id for card in cards}:
            raise ValidationError("Артикула нет в каталоге кабинета.")
        await self._repo.upsert(workspace_id, nm_id, metric, value)
        return SkuNormRead(nm_id=nm_id, metric=metric, value=value)

    async def clear_norm(self, *, workspace_id: uuid.UUID, nm_id: int, metric: MetricKey) -> None:
        """Remove an article's norm on one metric; a missing one is already cleared."""
        await self._repo.delete(workspace_id, nm_id, metric)
