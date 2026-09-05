"""The module's window onto the workspace's catalogue.

A test names a WB article, and an article this workspace does not own cannot be
rotated: the media upload would land on somebody else's card, or on nothing.
Until 2026-09-05 the article came straight off the request body and a test was
created against article `1`.

This is a thin wrapper over two loaders in the monitoring contract, and it exists
to be a **dependency**. The router used to call those loaders directly with the
request session, which worked and made the routes untestable above the
integration tier — the component tier's database tripwire is what said so. A
collaborator that can be replaced is also one whose absence is visible.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.contract import (
    WorkspaceCard,
    load_workspace_card,
    search_workspace_cards,
)


class SkuCatalogue:
    """Resolves and searches the catalogue cards a test may name."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def resolve(self, *, workspace_id: uuid.UUID, nm_id: int) -> WorkspaceCard | None:
        """Return the card for one article inside this workspace.

        Args:
            workspace_id: The workspace the article must belong to.
            nm_id: WB article.

        Returns:
            The card, or ``None`` when the workspace owns no such article.
        """
        return await load_workspace_card(self._session, workspace_id=workspace_id, nm_id=nm_id)

    async def search(
        self, *, workspace_id: uuid.UUID, needle: str, limit: int = 20
    ) -> list[WorkspaceCard]:
        """Return cards matching either article or the title.

        Args:
            workspace_id: Owning workspace.
            needle: Fragment of either article, or of the title.
            limit: Maximum cards to return.

        Returns:
            Matching cards, ranked by the monitoring loader: advertised cards
            first, then last week's ordered units descending. Both are
            properties of the card the picker cannot see, which is why the
            ordering is the loader's job and not the router's.
        """
        return await search_workspace_cards(
            self._session, workspace_id=workspace_id, needle=needle, limit=limit
        )
