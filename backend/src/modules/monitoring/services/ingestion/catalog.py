"""Ingestion of the product catalogue dimensions (cards + sizes)."""

from __future__ import annotations

import uuid

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.repos import ProductCardRepository, ProductSizeRepository
from src.modules.monitoring.schemas import CatalogIngestionResult

logger = get_logger(__name__)


class CatalogIngestion:
    """Persists the product-card identity and size dimensions."""

    def __init__(
        self,
        *,
        product_card_repo: ProductCardRepository,
        product_size_repo: ProductSizeRepository,
    ) -> None:
        """Inject the catalogue repositories used for persistence."""
        self._product_cards = product_card_repo
        self._product_sizes = product_size_repo

    async def ingest_catalog(
        self, cards: list[WBCard], *, workspace_id: uuid.UUID
    ) -> CatalogIngestionResult:
        """Upsert the product catalogue dimensions from Content API cards.

        Splits each card into its identity row (``product_card``: vendor code +
        title) and one size row per variant (``product_size``: chrt_id ->
        human ``tech_size``). Sizes are de-duplicated on ``chrt_id`` (last one
        wins) to avoid an ``ON CONFLICT``-target cardinality violation should WB
        repeat a ``chrtID`` across cards.

        Every card is stamped with the harvesting workspace: the catalogue was
        fetched with that workspace's own WB credentials, which is the
        authoritative proof of ownership backing all tenant scoping.

        Args:
            cards: Raw product cards from the content client.
            workspace_id: The workspace whose credentials produced ``cards``.

        Returns:
            A :class:`CatalogIngestionResult` tallying card + size rows persisted.
        """
        card_rows: list[dict[str, object]] = [
            {
                "nm_id": card.nm_id,
                "workspace_id": workspace_id,
                "vendor_code": card.vendor_code,
                "title": card.title,
            }
            for card in cards
        ]

        deduped_sizes: dict[int, dict[str, object]] = {
            size.chrt_id: {
                "chrt_id": size.chrt_id,
                "nm_id": card.nm_id,
                "tech_size": size.tech_size,
                "wb_size": size.wb_size,
            }
            for card in cards
            for size in card.sizes
        }

        card_count = await self._product_cards.upsert_many(card_rows)
        size_count = await self._product_sizes.upsert_many(list(deduped_sizes.values()))
        logger.info(
            "Ingested catalogue: %d product cards, %d sizes.",
            card_count,
            size_count,
        )
        return CatalogIngestionResult(product_card_rows=card_count, product_size_rows=size_count)
