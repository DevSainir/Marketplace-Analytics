"""FBS (seller-warehouse) stock, folded into the harvest's stock source.

FBS stock lives on a different WB surface from FBO stock, behind a different
token category, and is addressed by barcode instead of ``chrt_id``. All three
differences stop at this module: it hands the harvest ordinary
:class:`WBStockRow` values, so the same ingestion, the same
``monitoring.stock_snapshot`` grain, the same «Остатки по складам» panel and the
same finreports balance grid pick FBS up with no knowledge that it is FBS —
beyond the ``(FBS)`` in the configured warehouse label.

Why the label is configuration rather than WB's own name is spelled out on
``Settings.wb_fbs_warehouse_label``: ``warehouse_name`` is a primary-key column,
and the seller's warehouse names are editable working notes.
"""

from __future__ import annotations

from src.core.config import Settings
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.integrations.wildberries import build_marketplace_client
from src.integrations.wildberries.schemas import WBCard, WBFbsStockRow, WBStockRow
from src.modules.monitoring.repos import ProductSizeRepository

logger = get_logger(__name__)


def barcodes_from_cards(cards: list[WBCard] | None) -> dict[str, tuple[int, int]]:
    """Read ``barcode -> (nm_id, chrt_id)`` straight off freshly fetched cards.

    The same first-barcode-only rule the catalogue persists by, so the in-memory
    map and the stored column can never disagree about which barcode a size is
    asked for under.

    Args:
        cards: Content API cards, or ``None`` when the caller fetched none.

    Returns:
        A mapping covering every size whose card carries at least one barcode.
    """
    return {
        size.skus[0]: (card.nm_id, size.chrt_id)
        for card in cards or []
        for size in card.sizes
        if size.skus
    }


def fbs_rows_as_stock_rows(
    stocks: list[WBFbsStockRow],
    *,
    sizes_by_barcode: dict[str, tuple[int, int]],
    label: str,
) -> list[WBStockRow]:
    """Turn barcode-addressed FBS rows into ordinary warehouse stock rows.

    Args:
        stocks: What WB reported for the warehouse.
        sizes_by_barcode: ``barcode -> (nm_id, chrt_id)`` from our catalogue.
        label: The warehouse name these rows are filed under.

    Returns:
        One :class:`WBStockRow` per FBS row whose barcode we catalogue.
    """
    rows: list[WBStockRow] = []
    for stock in stocks:
        known = sizes_by_barcode.get(stock.sku)
        if known is None:
            # WB echoed a barcode we did not ask for; nothing sane to file it
            # under, and inventing an nm_id would corrupt a SKU's stock total.
            continue
        nm_id, chrt_id = known
        rows.append(
            WBStockRow(
                nm_id=nm_id,
                chrt_id=chrt_id,
                warehouse_name=label,
                region_name="FBS",
                quantity=stock.amount,
                # FBS stock sits in the seller's own warehouse: WB moves none of
                # it, so there is no in-transit leg to report. Zero here is the
                # true value, not a missing one.
                in_way_to_client=0,
                in_way_from_client=0,
            )
        )
    return rows


async def fetch_fbs_stock_rows(
    settings: Settings,
    *,
    token: str,
    nm_ids: list[int],
    cards: list[WBCard] | None = None,
) -> list[WBStockRow]:
    """Fetch the enabled FBS warehouse's stock as ordinary stock rows.

    Returns an empty list (rather than raising) for the two ways FBS is simply
    not in play: no «Маркетплейс» token on the workspace, and FBS harvesting
    switched off via ``wb_fbs_warehouse_id = 0``. A workspace without the token
    is the normal case — only the seller who ships FBS has one — so this must
    not read as a failure.

    Args:
        settings: Enabled warehouse id, its display label, and transport config.
        token: The workspace's «Маркетплейс»-scope token.
        nm_ids: The SKUs this harvest covers; their barcodes are the query.
        cards: Content API cards the caller already fetched, if any. They carry
            the barcodes too, and they are read FIRST because the catalogue rows
            for this run are only written later in the same transaction —
            without them the first harvest after the barcode column shipped
            would find it blank and skip FBS for a day.

    Returns:
        One :class:`WBStockRow` per size WB reports at the warehouse, carrying
        the configured label as ``warehouse_name``.

    Raises:
        IntegrationError: Propagated from the client when WB answers with an
            unexpected shape or the rate budget cannot be met — the caller
            records it as a failed source like any other.
    """
    warehouse_id = settings.wb_fbs_warehouse_id
    if not token or not warehouse_id or not nm_ids:
        return []

    async with AsyncSessionLocal() as session:
        sizes_by_barcode = await ProductSizeRepository(session).get_sizes_by_barcode(nm_ids)
    sizes_by_barcode |= barcodes_from_cards(cards)
    if not sizes_by_barcode:
        # Every catalogue row predates the barcode column; the next content
        # sync fills it. Logged because "no FBS stock" and "no barcodes to ask
        # about" look identical downstream, and only one of them is a fact.
        logger.info(
            "No catalogued barcodes for %d SKUs — skipping the FBS stock read.", len(nm_ids)
        )
        return []

    async with build_marketplace_client(settings, token=token) as client:
        stocks = await client.fetch_stocks(warehouse_id=warehouse_id, skus=sorted(sizes_by_barcode))

    rows = fbs_rows_as_stock_rows(
        stocks,
        sizes_by_barcode=sizes_by_barcode,
        label=settings.wb_fbs_warehouse_label,
    )
    logger.info("FBS warehouse %s: %d stock rows.", warehouse_id, len(rows))
    return rows
