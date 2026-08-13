"""Unit tests for folding FBS stock into ordinary warehouse stock rows.

FBS reaches us barcode-addressed from a separate WB surface, and everything
downstream — the «Остатки по складам» panel, the finreports balance grid, the
out-of-stock masking — reads one table keyed by ``(nm_id, warehouse, chrt_id)``.
This mapping is the whole of the seam, so what it does with an unmatched
barcode and where the size identity comes from are worth pinning.
"""

from __future__ import annotations

from src.integrations.wildberries.schemas import WBCard, WBCardSize, WBFbsStockRow
from src.modules.monitoring.tasks.fbs import barcodes_from_cards, fbs_rows_as_stock_rows

#: Two real sizes of nm 995716075 as catalogued locally.
_SIZES: dict[str, tuple[int, int]] = {
    "2046161763208": (995716075, 965033858),
    "2046161763215": (995716075, 965033859),
}
_LABEL = "Москва (Внуково) (FBS)"


def test_stock_is_filed_under_the_configured_warehouse_label() -> None:
    """Rows carry the configured label, not WB's seller-authored warehouse name.

    ``warehouse_name`` is a primary-key column and the join key for «Отгрузить»
    marks, so it must not change when someone edits the warehouse name in the
    WB portal.
    """
    stocks = [WBFbsStockRow(sku="2046161763208", chrt_id=965033858, amount=480)]

    rows = fbs_rows_as_stock_rows(stocks, sizes_by_barcode=_SIZES, label=_LABEL)

    assert [(r.nm_id, r.chrt_id, r.warehouse_name, r.quantity) for r in rows] == [
        (995716075, 965033858, _LABEL, 480)
    ]


def test_a_barcode_we_do_not_catalogue_is_dropped() -> None:
    """An unrecognised barcode yields no row rather than a guessed SKU.

    There is no honest ``nm_id`` for it, and inventing one would silently add
    units to some other SKU's stock total.
    """
    stocks = [
        WBFbsStockRow(sku="2046161763208", chrt_id=965033858, amount=480),
        WBFbsStockRow(sku="0000000000000", chrt_id=999, amount=99),
    ]

    rows = fbs_rows_as_stock_rows(stocks, sizes_by_barcode=_SIZES, label=_LABEL)

    assert [r.nm_id for r in rows] == [995716075]


def test_the_size_identity_comes_from_our_catalogue_not_from_wb() -> None:
    """``chrt_id`` is resolved locally, so it always joins ``product_size``.

    WB returns a ``chrtId`` of its own; if the two ever disagree, the label
    lookup and the stock row have to agree with each other, not with WB.
    """
    stocks = [WBFbsStockRow(sku="2046161763215", chrt_id=111111111, amount=24)]

    rows = fbs_rows_as_stock_rows(stocks, sizes_by_barcode=_SIZES, label=_LABEL)

    assert rows[0].chrt_id == 965033859


def test_barcodes_are_readable_from_cards_before_they_are_persisted() -> None:
    """A harvest that fetched cards can query FBS on the same run.

    The catalogue rows carrying the barcodes are written later in the same
    transaction, so relying on the stored column alone would skip FBS for a
    whole day after the column first shipped — and again for any new SKU.
    """
    cards = [
        WBCard(
            nmID=995716075,
            sizes=[
                WBCardSize(chrtID=965033858, skus=["2046161763208"]),
                WBCardSize(chrtID=965033859, skus=[]),
            ],
        )
    ]

    barcodes = barcodes_from_cards(cards)

    assert barcodes == {"2046161763208": (995716075, 965033858)}


def test_fbs_rows_report_no_goods_in_transit() -> None:
    """The in-transit columns are zero because FBS has no in-transit leg.

    WB never moves FBS stock, so a blank here is the true value — not an
    unknown one that some later step should try to fill in.
    """
    stocks = [WBFbsStockRow(sku="2046161763208", chrt_id=965033858, amount=480)]

    rows = fbs_rows_as_stock_rows(stocks, sizes_by_barcode=_SIZES, label=_LABEL)

    assert (rows[0].in_way_to_client, rows[0].in_way_from_client) == (0, 0)
