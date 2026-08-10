"""The «Баланс по товарным остаткам» grid: what the backend is responsible for.

Its job is the pricing, the row order and the caveats — the totals belong to the
client that draws the panels (they change with every mark and every keystroke in
the search, without a round trip). Every way to get the pricing wrong produces a
plausible number rather than an error: pricing an uncosted SKU at zero, ranking
rows on stock the seller took out of the count, or carrying yesterday's snapshot
into a day WB never reported.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.finreports.services import build_balance

DAY = date(2026, 8, 3)
SPAN = (date(2026, 1, 1), date(2026, 8, 3))

NM_BRUKI = 953770957
NM_SHORTS = 611450917


def _balance(**overrides: object) -> object:
    """Build a grid over one costed SKU in two warehouses, unless overridden."""
    kwargs: dict[str, object] = {
        "stat_date": DAY,
        "stock": {(NM_BRUKI, "Тула"): 72, (NM_BRUKI, "Коледино"): 8},
        "costs": {NM_BRUKI: Decimal("800")},
        "identity": {NM_BRUKI: ("m-trx01-blk", "Брюки", "NORTH LINE")},
        "vendor_codes": {},
        "pinned_skus": set(),
        "pinned_warehouses": set(),
        "uncounted_warehouses": set(),
        "currency": "KGS",
        "span": SPAN,
    }
    kwargs.update(overrides)
    return build_balance(**kwargs)  # type: ignore[arg-type]


def test_a_cell_is_its_units_priced_at_the_sku_cost() -> None:
    """The balance of a cell is quantity x cost price — the table's whole subject.

    72 units at 800 is 57 600 сом sitting in Тула, and that is the figure a
    seller reads next to the «72».
    """
    grid = _balance()

    tula = next(cell for cell in grid.rows[0].cells if cell.warehouse_name == "Тула")

    assert tula.quantity == 72
    assert tula.balance == Decimal("57600")


def test_an_uncosted_sku_keeps_its_units_and_reports_no_money() -> None:
    """A SKU with no cost on file gets quantities and ``None`` for every money.

    Pricing it at zero would quietly shrink the balance of the whole warehouse;
    the cell instead says «unknown» and the row is counted in ``uncosted_count``
    so the panels can be read as the partial sums they are.
    """
    grid = _balance(
        stock={(NM_BRUKI, "Тула"): 72, (NM_SHORTS, "Тула"): 40},
        identity={
            NM_BRUKI: ("m-trx01-blk", "Брюки", "NORTH LINE"),
            NM_SHORTS: ("m-wdx02-wht", "Шорты", "NORTH LINE"),
        },
    )

    uncosted = next(row for row in grid.rows if row.nm_id == NM_SHORTS)

    assert uncosted.cost_price is None
    assert [(c.quantity, c.balance) for c in uncosted.cells] == [(40, None)]
    assert grid.uncosted_count == 1


def test_rows_are_ranked_on_counted_stock_only() -> None:
    """A warehouse marked «Не считать» decides neither a total nor the order.

    Its cells are still priced and still shown — the seller wants to see what is
    lying there — but a row must not be promoted by stock the seller has already
    declared out of the count.
    """
    grid = _balance(
        stock={
            (NM_BRUKI, "СЦ Брак"): 500,
            (NM_BRUKI, "Тула"): 1,
            (NM_SHORTS, "Тула"): 10,
        },
        costs={NM_BRUKI: Decimal("800"), NM_SHORTS: Decimal("300")},
        identity={
            NM_BRUKI: ("m-trx01-blk", "Брюки", "NORTH LINE"),
            NM_SHORTS: ("m-wdx02-wht", "Шорты", "NORTH LINE"),
        },
        uncounted_warehouses={"СЦ Брак"},
    )

    assert [row.nm_id for row in grid.rows] == [NM_SHORTS, NM_BRUKI]
    brak = next(c for c in grid.rows[1].cells if c.warehouse_name == "СЦ Брак")
    assert brak.balance == Decimal("400000")
    assert grid.uncounted_warehouses == ["СЦ Брак"]


def test_the_persisted_marks_travel_with_the_grid() -> None:
    """The client applies the marks, so it has to be told what they are.

    Pins order the rows and columns on screen and «Не считать» drops a column
    from the totals; all three are answered from the persisted marks, not
    re-derived per request from anything on the client.
    """
    grid = _balance(pinned_skus={NM_BRUKI}, pinned_warehouses={"Коледино"})

    assert grid.pinned_skus == [NM_BRUKI]
    assert grid.pinned_warehouses == ["Коледино"]


def test_a_day_without_a_snapshot_is_empty_and_says_which_days_exist() -> None:
    """A day WB never reported renders empty, never the neighbouring day's stock.

    Stock is not carried over: silently showing the previous snapshot under
    today's date would report goods as present after they shipped.
    """
    grid = _balance(stat_date=date(2026, 7, 4), stock={})

    assert grid.rows == []
    assert "нет снимка остатков" in grid.notes[0]
    assert "2026-01-01" in grid.notes[0]


def test_a_sku_that_never_settled_a_row_is_named_by_its_catalogue_code() -> None:
    """Fresh stock that has never sold still gets a name, not a bare nm_id.

    Its identity is absent from the settlement rows the P&L names SKUs from, so
    the catalogue «Артикул продавца» stands in.
    """
    grid = _balance(
        stock={(NM_SHORTS, "Тула"): 12},
        costs={},
        identity={},
        vendor_codes={NM_SHORTS: "m-wdx02-wht"},
    )

    assert grid.rows[0].sa_name == "m-wdx02-wht"
