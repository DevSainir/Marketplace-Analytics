"""Unit tests for folding FBS stock into ordinary warehouse stock rows.

FBS reaches us barcode-addressed from a separate WB surface, and everything
downstream — the «Остатки по складам» panel, the finreports balance grid, the
out-of-stock masking — reads one table keyed by ``(nm_id, warehouse, chrt_id)``.
This mapping is the whole of the seam, so what it does with an unmatched
barcode and where the size identity comes from are worth pinning. The seller's
warehouses are discovered rather than configured, so the labelling rule and the
tolerance of a warehouse that will not answer are pinned here too.
"""

from __future__ import annotations

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.schemas import (
    WBCard,
    WBCardSize,
    WBFbsStockRow,
    WBFbsWarehouse,
)
from src.modules.monitoring.models import LABEL_MAX_LENGTH
from src.modules.monitoring.tasks.fbs import (
    barcodes_from_cards,
    fbs_rows_as_stock_rows,
    label_for,
    read_each_warehouse,
)

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


# --------------------------------------------------------------------------- #
# Discovery: every warehouse the seller owns is read, and labelled once.
# --------------------------------------------------------------------------- #
def _warehouse(warehouse_id: int, name: str) -> WBFbsWarehouse:
    """A warehouse as WB lists it."""
    return WBFbsWarehouse(id=warehouse_id, name=name, office_id=236, cargo_type=1, delivery_type=1)


def test_a_configured_label_wins_over_the_sellers_own_name() -> None:
    """The name WB reports is a working note; the configured label is the header."""
    warehouse = _warehouse(9945803, "Иван  - Москва (Внуково) НЕ УДАЛЯТЬ!!!")

    assert label_for(warehouse, {9945803: _LABEL}) == _LABEL


def test_an_unconfigured_warehouse_is_labelled_from_wbs_name() -> None:
    """A newly opened warehouse is harvested at once rather than waiting on config.

    Its label is WB's name with the seller's stray spacing collapsed, marked
    ``(FBS)`` like every other seller warehouse.
    """
    warehouse = _warehouse(3300771, "Тула  склад")

    assert label_for(warehouse, {}) == "Тула склад (FBS)"


def test_a_label_always_fits_the_column_it_is_filed_into() -> None:
    """``warehouse_name`` is ``String(128)``: a longer label could not be stored."""
    warehouse = _warehouse(3300772, "Ы" * 400)

    label = label_for(warehouse, {})

    assert len(label) == LABEL_MAX_LENGTH
    assert label.endswith(" (FBS)")


def test_a_nameless_warehouse_falls_back_to_its_id() -> None:
    """Unnamed in WB — still addressable, and still distinct from its siblings."""
    assert label_for(_warehouse(3300773, ""), {}) == "Склад 3300773 (FBS)"


class _StubMarketplace:
    """A marketplace client whose named warehouses refuse to be read."""

    def __init__(self, *, failing: set[int]) -> None:
        self._failing = failing
        self.asked: list[int] = []

    async def fetch_stocks(self, *, warehouse_id: int, skus: list[str]) -> list[WBFbsStockRow]:
        """Answer with one row per warehouse, or fail if it is a named one."""
        self.asked.append(warehouse_id)
        if warehouse_id in self._failing:
            raise IntegrationError(f"warehouse {warehouse_id} is gone")
        return [WBFbsStockRow(sku=skus[0], chrt_id=965033858, amount=warehouse_id)]


async def test_one_dead_warehouse_does_not_cost_us_the_others() -> None:
    """A warehouse that cannot be read is skipped and named, not fatal.

    The account keeps test/cross-border stubs beside its real warehouses; one of
    them answering badly must not turn a good FBS pass into no stock at all.
    """
    client = _StubMarketplace(failing={2})

    read, unread, failures = await read_each_warehouse(
        client,  # type: ignore[arg-type]
        [(1, "Москва (FBS)"), (2, "Заглушка (FBS)"), (3, "Тула (FBS)")],
        ["2046161763208"],
    )

    assert [warehouse_id for warehouse_id, _, _ in read] == [1, 3]
    assert unread == ["Заглушка (FBS)"]
    assert len(failures) == 1
    # The failure did not stop the sweep of the remaining warehouses.
    assert client.asked == [1, 2, 3]
