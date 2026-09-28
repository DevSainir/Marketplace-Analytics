"""Folding SKU-day facts into the heatmap's rows and its «Итого» line."""

from __future__ import annotations

from datetime import date

from src.modules.heatmap.services.metrics import Facts
from src.modules.heatmap.services.periods import build_columns
from src.modules.heatmap.services.table import (
    UNGROUPED,
    UNNAMED,
    GroupSpec,
    build_row_specs,
    build_rows,
    fold_sku_days,
)
from src.modules.monitoring.contract import CatalogCard

_DAY = date(2026, 9, 23)
_COLUMNS = build_columns(_DAY, _DAY, "day")


def _card(nm_id: int, *, subject: str = "Костюмы", brand: str = "NEVA") -> CatalogCard:
    """A catalogue card with just enough identity for a label."""
    return CatalogCard(
        nm_id=nm_id,
        vendor_code=f"art-{nm_id}",
        title="",
        photo_url="",
        subject_name=subject,
        brand=brand,
    )


def _orders(count: int) -> Facts:
    """A funnel day with ``count`` orders."""
    return Facts(funnel_days=1, orders=count)


def test_an_article_in_two_groups_is_counted_once_in_the_totals() -> None:
    """Groups overlap; the «Итого» line folds distinct articles, not rows."""
    facts = {(1, _DAY): _orders(5), (2, _DAY): _orders(3)}
    grid = fold_sku_days(facts, _COLUMNS)
    groups = [
        GroupSpec(key="a", name="Двойки", nm_ids=frozenset({1, 2})),
        GroupSpec(key="b", name="Хиты", nm_ids=frozenset({1})),
    ]
    specs = build_row_specs("group", nm_ids=grid.cells, cards={}, groups=groups)

    totals, _rows = build_rows(specs, grid, width=1, metrics=("orders", None), rank={})

    assert totals.values == [8.0]


def test_articles_in_no_group_get_a_row_of_their_own() -> None:
    """Cutting by group must not silently drop the articles nobody grouped."""
    facts = {(1, _DAY): _orders(5), (2, _DAY): _orders(3)}
    grid = fold_sku_days(facts, _COLUMNS)
    groups = [GroupSpec(key="a", name="Двойки", nm_ids=frozenset({1}))]

    specs = build_row_specs("group", nm_ids=grid.cells, cards={}, groups=groups)

    assert [(spec.label, spec.nm_ids) for spec in specs] == [
        ("Двойки", frozenset({1})),
        (UNGROUPED, frozenset({2})),
    ]


def test_an_article_wb_gave_no_subject_is_grouped_as_unnamed() -> None:
    """A blank subject is its own row with a readable label, not an empty string."""
    cards = {1: _card(1, subject=""), 2: _card(2, subject="Платья")}

    specs = build_row_specs("subject", nm_ids=[1, 2], cards=cards)

    assert sorted(spec.label for spec in specs) == [UNNAMED, "Платья"]


def test_a_category_row_sums_its_articles() -> None:
    """A category's orders are its articles' orders, folded before the metric is read."""
    cards = {1: _card(1), 2: _card(2), 3: _card(3, subject="Платья")}
    facts = {(1, _DAY): _orders(5), (2, _DAY): _orders(3), (3, _DAY): _orders(1)}
    grid = fold_sku_days(facts, _COLUMNS)
    specs = build_row_specs("subject", nm_ids=grid.cells, cards=cards)

    _totals, rows = build_rows(specs, grid, width=1, metrics=("orders", None), rank={1: 5, 2: 3})

    assert [(row.label, row.total, row.sku_count) for row in rows] == [
        ("Костюмы", 8.0, 2),
        ("Платья", 1.0, 1),
    ]


def test_rows_are_ordered_by_how_much_they_sold() -> None:
    """The default order is popularity — ordered units over the window, most first."""
    cards = {1: _card(1), 2: _card(2)}
    facts = {(1, _DAY): _orders(1), (2, _DAY): _orders(9)}
    grid = fold_sku_days(facts, _COLUMNS)
    specs = build_row_specs("sku", nm_ids=grid.cells, cards=cards)

    _totals, rows = build_rows(specs, grid, width=1, metrics=("orders", None), rank={1: 1, 2: 9})

    assert [row.nm_id for row in rows] == [2, 1]


def test_a_second_metric_travels_in_its_own_column_of_values() -> None:
    """The lower number of a two-metric cell is the second metric, read off the same fold."""
    cards = {1: _card(1)}
    facts = {(1, _DAY): Facts(funnel_days=1, orders=4, carts=8, opens=40)}
    grid = fold_sku_days(facts, _COLUMNS)
    specs = build_row_specs("sku", nm_ids=grid.cells, cards=cards)

    _totals, rows = build_rows(
        specs, grid, width=1, metrics=("orders", "order_conversion"), rank={}
    )

    assert rows[0].values == [4.0]
    assert rows[0].values2 == [50.0]


def test_a_day_outside_the_window_is_ignored() -> None:
    """A fact dated outside every column cannot leak into a row's total."""
    facts = {(1, _DAY): _orders(2), (1, date(2026, 9, 1)): _orders(100)}

    grid = fold_sku_days(facts, _COLUMNS)

    assert grid.totals[1].orders == 2


def test_a_settled_day_without_sales_reads_zero_revenue() -> None:
    """A settled day with no sales is zero; a day WB has not settled says nothing."""
    days = build_columns(date(2026, 9, 22), _DAY, "day")
    facts = {(1, date(2026, 9, 22)): Facts(finance_known=True, sold_units=2)}
    grid = fold_sku_days(facts, days)
    specs = build_row_specs("sku", nm_ids=grid.cells, cards={1: _card(1)})

    _totals, rows = build_rows(
        specs, grid, width=2, metrics=("sales", None), rank={}, settled=[True, False]
    )

    assert rows[0].values == [2.0, None]


def test_a_settled_day_without_facts_is_zero_not_blank() -> None:
    """The newest column (23.09) is settled but the article sold nothing on it."""
    days = build_columns(date(2026, 9, 22), _DAY, "day")
    facts = {(1, date(2026, 9, 22)): Facts(finance_known=True, sold_units=2)}
    grid = fold_sku_days(facts, days)
    specs = build_row_specs("sku", nm_ids=grid.cells, cards={1: _card(1)})

    _totals, rows = build_rows(
        specs, grid, width=2, metrics=("sales", None), rank={}, settled=[True, True]
    )

    assert rows[0].values == [2.0, 0.0]
