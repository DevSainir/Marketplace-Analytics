"""Ingestion of the product catalogue dimensions (cards + sizes)."""

from __future__ import annotations

import uuid

from src.core.logging import get_logger
from src.integrations.wildberries.photos import is_wb_photo_url
from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.models.products import BRAND_MAX_LENGTH, SUBJECT_MAX_LENGTH
from src.modules.monitoring.repos import ProductCardRepository, ProductSizeRepository
from src.modules.monitoring.schemas import CatalogIngestionResult

logger = get_logger(__name__)


def _main_photo(card: WBCard) -> str:
    """Return the card's main gallery image URL, or ``""`` when there is none.

    ``photos[0]`` is the main slot and ``.best`` is the largest rendition WB
    actually serves — never ``hq``, which every card advertises and the CDN
    404s (measured 2026-09-07; see :class:`WBCardPhoto`).

    The host is checked because this value is stored to be rendered as an
    ``<img src>`` on three screens. A URL out of a WB response is outside the
    trust boundary however well authenticated the call was, and an unexpected
    host here would be a third party told which of our users is looking at
    which card, from inside our own page. A card whose URL fails the check is
    stored photo-less rather than skipped: it still has to appear in the
    catalogue, and a missing thumbnail is a smaller lie than a missing SKU.

    Args:
        card: One parsed Content API card.

    Returns:
        An https URL on a WB image host, or the empty string.
    """
    if not card.photos:
        return ""
    url = card.photos[0].best
    if not url or not is_wb_photo_url(url):
        return ""
    return url


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

        Splits each card into its identity row (``product_card``: vendor code,
        title and main photo) and one size row per variant (``product_size``: chrt_id ->
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
                "photo_url": _main_photo(card),
                "subject_name": card.subject_name[:SUBJECT_MAX_LENGTH],
                "brand": card.brand[:BRAND_MAX_LENGTH],
            }
            for card in cards
        ]

        deduped_sizes: dict[int, dict[str, object]] = {
            size.chrt_id: {
                "chrt_id": size.chrt_id,
                "nm_id": card.nm_id,
                "tech_size": size.tech_size,
                "wb_size": size.wb_size,
                # First barcode only — the FBS stock query needs one per size,
                # and WB echoes ``chrtId`` back, so extras add no reachable rows.
                "barcode": size.skus[0] if size.skus else "",
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
