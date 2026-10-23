"""FBS (seller-warehouse) stock, folded into the harvest's stock source.

FBS stock lives on a different WB surface from FBO stock, behind a different
token category, and is addressed by barcode instead of ``chrt_id``. All three
differences stop at this module: it hands the harvest ordinary
:class:`WBStockRow` values, so the same ingestion, the same
``monitoring.stock_snapshot`` grain, the same "Stock by warehouse" panel and the
same finreports balance grid pick FBS up with no knowledge that it is FBS —
beyond the ``(FBS)`` in the warehouse label.

**Every warehouse the seller owns is read.** The set is discovered from WB on
each run rather than configured, so opening a warehouse in the portal is enough
to have it harvested; each one costs one call against the marketplace surface's
rate budget (20 tokens — the tightest of any WB surface we use), which is why
they are read in sequence and why a warehouse that answers badly is skipped
rather than allowed to take the others down with it.

The LABEL a warehouse's stock is filed under is resolved once, on first sight,
and frozen in ``monitoring.fbs_warehouse`` — see
:class:`~src.modules.monitoring.models.fbs_warehouses.FbsWarehouse` for why a
seller's own warehouse name cannot be trusted as a key.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.config import Settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries import build_marketplace_client
from src.integrations.wildberries.clients.marketplace import WBMarketplaceClient
from src.integrations.wildberries.schemas import (
    WBCard,
    WBFbsStockRow,
    WBFbsWarehouse,
    WBStockRow,
)
from src.modules.monitoring.models import LABEL_MAX_LENGTH
from src.modules.monitoring.repos import FbsWarehouseRepository, ProductSizeRepository

logger = get_logger(__name__)

#: Appended to every FBS warehouse label, so a column header says which side of
#: the business a warehouse belongs to without the reader knowing WB ids.
_FBS_SUFFIX = " (FBS)"


@dataclass(frozen=True, slots=True)
class FbsStock:
    """What one FBS pass read, and which warehouses it could not read.

    ``unread`` names the labels whose read failed while others succeeded. The
    harvest spares exactly those from the absence-means-zero sweep: sweeping a
    warehouse we simply did not reach would report the seller's stock as
    emptied rather than unread.
    """

    rows: list[WBStockRow]
    unread: tuple[str, ...] = ()


def label_for(warehouse: WBFbsWarehouse, configured: dict[int, str]) -> str:
    """The label a NEWLY discovered warehouse's stock will be filed under.

    A configured label wins (see ``Settings.wb_fbs_warehouse_labels``);
    otherwise WB's own name is used, with its spacing collapsed — the seller's
    names carry double spaces and working notes, and this is a column header.
    A nameless warehouse falls back to its id, which is at least addressable.

    Only ever consulted for a warehouse we have never seen: once stored, the
    label is frozen (:meth:`FbsWarehouseRepository.remember`).
    """
    configured_label = configured.get(warehouse.id)
    if configured_label:
        return configured_label[:LABEL_MAX_LENGTH]
    name = " ".join((warehouse.name or "").split())
    if not name:
        return f"Warehouse {warehouse.id}{_FBS_SUFFIX}"
    return f"{name[: LABEL_MAX_LENGTH - len(_FBS_SUFFIX)]}{_FBS_SUFFIX}"


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


async def remembered_warehouses(
    warehouses: list[WBFbsWarehouse], settings: Settings
) -> list[tuple[int, str]]:
    """Record what WB listed and return ``(warehouse_id, label)`` for each.

    New warehouses are stored with a resolved label (:func:`label_for`); known
    ones keep the label they were first stored under, whatever WB calls them
    now. Newly discovered ones are logged: a warehouse appearing on its own is
    the kind of thing that should be visible in the harvest log rather than
    only in a stock column that grew overnight.
    """
    async with AsyncSessionLocal() as session:
        repo = FbsWarehouseRepository(session)
        known_ids = {row.warehouse_id for row in await repo.list_all()}
        resolved: list[tuple[int, str]] = []
        for warehouse in warehouses:
            stored = await repo.remember(
                warehouse_id=warehouse.id,
                label=label_for(warehouse, settings.wb_fbs_warehouse_labels),
                wb_name=warehouse.name or "",
            )
            if warehouse.id not in known_ids:
                logger.info(
                    "Discovered FBS warehouse %s (%r) — filing its stock under %r.",
                    warehouse.id,
                    warehouse.name,
                    stored.label,
                )
            resolved.append((warehouse.id, stored.label))
        await session.commit()
    return resolved


async def known_warehouse_labels() -> tuple[str, ...]:
    """Every label FBS stock has ever been filed under.

    What the harvest spares from its stale-row sweep when the FBS source fails
    outright: without a successful read there is no way to tell an emptied
    warehouse from an unread one, and the sweep must not decide that question.
    """
    async with AsyncSessionLocal() as session:
        return tuple(row.label for row in await FbsWarehouseRepository(session).list_all())


async def read_each_warehouse(
    client: WBMarketplaceClient, warehouses: list[tuple[int, str]], barcodes: list[str]
) -> tuple[list[tuple[int, str, list[WBFbsStockRow]]], list[str], list[IntegrationError]]:
    """Read each warehouse in turn, tolerating individual failures.

    Sequential on purpose: the marketplace surface refills 20 tokens slowly, and
    firing every warehouse at once would only queue them inside the rate gate
    while making a partial failure harder to attribute.
    """
    read: list[tuple[int, str, list[WBFbsStockRow]]] = []
    unread: list[str] = []
    failures: list[IntegrationError] = []
    for warehouse_id, label in warehouses:
        try:
            stocks = await client.fetch_stocks(warehouse_id=warehouse_id, skus=barcodes)
        except IntegrationError as exc:
            # One warehouse answering badly (a deleted stub, a scope quirk) must
            # not cost the seller the warehouses that DID answer.
            logger.warning("FBS warehouse %s (%s) could not be read: %s", warehouse_id, label, exc)
            unread.append(label)
            failures.append(exc)
            continue
        read.append((warehouse_id, label, stocks))
    return read, unread, failures


async def fetch_fbs_stock_rows(
    settings: Settings,
    *,
    token: str,
    nm_ids: list[int],
    cards: list[WBCard] | None = None,
) -> FbsStock:
    """Fetch every FBS warehouse's stock as ordinary stock rows.

    The seller's warehouses are discovered from WB on each run, so a warehouse
    opened in the portal is harvested without a deploy; each is read in turn and
    filed under its own label.

    Returns an empty result (rather than raising) for the two ways FBS is simply
    not in play: no "Marketplace" token on the workspace, and FBS harvesting
    switched off via ``wb_fbs_harvest_enabled``. A workspace without the token
    is the normal case — only the seller who ships FBS has one — so this must
    not read as a failure.

    Args:
        settings: Label overrides, the FBS switch, and transport config.
        token: The workspace's "Marketplace"-scope token.
        nm_ids: The SKUs this harvest covers; their barcodes are the query.
        cards: Content API cards the caller already fetched, if any. They carry
            the barcodes too, and they are read FIRST because the catalogue rows
            for this run are only written later in the same transaction —
            without them the first harvest after the barcode column shipped
            would find it blank and skip FBS for a day.

    Returns:
        The stock rows read across all warehouses, plus the labels of any
        warehouse whose own read failed while others succeeded.

    Raises:
        IntegrationError: When the warehouse list itself cannot be read, or when
            EVERY warehouse read failed — the caller records it as a failed
            source like any other, and spares all FBS labels from its sweep.
    """
    if not token or not settings.wb_fbs_harvest_enabled or not nm_ids:
        return FbsStock(rows=[])

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
        return FbsStock(rows=[])

    barcodes = sorted(sizes_by_barcode)
    async with build_marketplace_client(settings, token=token) as client:
        warehouses = await remembered_warehouses(await client.fetch_warehouses(), settings)
        if not warehouses:
            logger.info("The seller owns no FBS warehouses — nothing to read.")
            return FbsStock(rows=[])
        read, unread, failures = await read_each_warehouse(client, warehouses, barcodes)

    if failures and not read:
        # Nothing at all came back: report it as a source failure so the sweep
        # spares every FBS label, rather than silently returning no stock.
        raise failures[0]

    rows: list[WBStockRow] = []
    for warehouse_id, label, stocks in read:
        warehouse_rows = fbs_rows_as_stock_rows(
            stocks, sizes_by_barcode=sizes_by_barcode, label=label
        )
        logger.info(
            "FBS warehouse %s (%s): %d stock rows.", warehouse_id, label, len(warehouse_rows)
        )
        rows.extend(warehouse_rows)
    return FbsStock(rows=rows, unread=tuple(unread))
