"""Shared repository plumbing for the Monitoring module.

Provides an async, idempotent bulk-upsert helper built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so that re-harvesting the same window
overwrites prior values instead of raising primary-key violations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base
from src.core.upsert import upsert_rows
from src.modules.monitoring.models import ProductCard


def workspace_sku_select(workspace_id: uuid.UUID) -> Select[tuple[int]]:
    """Build the ``nm_id`` semijoin restricting a query to one workspace's SKUs.

    ``product_card`` is the authoritative SKU -> workspace registry (see
    :class:`~src.modules.monitoring.models.products.ProductCard`). Every
    cross-SKU aggregate uses this as an ``IN`` subquery so SKUs of other
    workspaces — or unclaimed legacy rows — never surface.

    Args:
        workspace_id: The active workspace.

    Returns:
        A ``SELECT nm_id FROM product_card WHERE workspace_id = :ws`` statement
        suitable for ``Column.in_()``.
    """
    return select(ProductCard.nm_id).where(ProductCard.workspace_id == workspace_id)


class BaseRepository:
    """Common async persistence helpers shared by monitoring repositories."""

    #: ORM model this repository manages. Subclasses must override.
    model: type[Base]

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def bulk_upsert(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        """Insert rows, updating the given columns on primary-key conflict.

        Args:
            rows: Column->value mappings to persist. An empty sequence is a
                no-op that returns ``0``.
            conflict_columns: Columns forming the conflict target (the primary
                key / unique index).
            update_columns: Columns to overwrite with the incoming values when a
                conflicting row already exists.

        Returns:
            The number of rows submitted for upsert.
        """
        return await upsert_rows(
            self._session,
            self.model,
            rows,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
        )
