"""Folding SKU-day facts into the grid: which rows exist, and what each cell sums.

Pure — facts, catalogue and groups in, rows out — so every rule of the grid is
pinned by a unit test rather than by a database.

The rules worth stating:

* **A row is a set of articles.** An article row is a set of one; a category,
  a brand or a group is a larger one. Cells are the articles' facts folded with
  :func:`~.metrics.merge_skus`, and the metric is read off the fold — never off
  the articles' own metric values.
* **"Total" counts every article once.** Groups may overlap (one article can
  sit in two), so the totals are folded from the distinct articles of the
  selection, not from the rows — otherwise an article in two groups would be
  counted twice at the top of the table.
* **A row with no facts in the window is dropped.** A category whose articles
  did nothing is noise at the bottom of a heatmap, and the article filter is
  where a seller looks for a card that has gone silent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from src.modules.heatmap.schemas import GroupBy, HeatmapRow
from src.modules.heatmap.services.metrics import (
    SPEND_MONEY,
    Facts,
    merge_days,
    merge_skus,
    read_metric,
    spend_unit,
)
from src.modules.heatmap.services.periods import column_of_day
from src.modules.monitoring.contract import CatalogCard

#: Label of the row for articles WB gave no subject or brand.
UNNAMED = "(not set)"
#: Label of the row for articles in no group.
UNGROUPED = "No group"


@dataclass(frozen=True, slots=True)
class RowSpec:
    """One row before its cells are computed: a label and the articles it covers."""

    key: str
    label: str
    nm_ids: frozenset[int]
    card: CatalogCard | None = None


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """A seller-defined group, as the grid needs it."""

    key: str
    name: str
    nm_ids: frozenset[int]


def build_row_specs(
    group_by: GroupBy,
    *,
    nm_ids: Iterable[int],
    cards: Mapping[int, CatalogCard],
    groups: Iterable[GroupSpec] = (),
) -> list[RowSpec]:
    """Decide the rows for the selected articles and the chosen cut.

    Args:
        group_by: What one row stands for.
        nm_ids: The selected articles that have facts in the window.
        cards: Catalogue identity per article, for labels and names.
        groups: The workspace's groups, used when cutting by group.
    """
    selected = frozenset(nm_ids)
    if group_by == "sku":
        return [
            RowSpec(
                key=str(nm),
                label=cards[nm].vendor_code if nm in cards else f"SKU {nm}",
                nm_ids=frozenset({nm}),
                card=cards.get(nm),
            )
            for nm in sorted(selected)
        ]
    if group_by == "group":
        specs: list[RowSpec] = []
        grouped: set[int] = set()
        for group in groups:
            members = group.nm_ids & selected
            grouped |= members
            if members:
                specs.append(RowSpec(key=group.key, label=group.name, nm_ids=members))
        rest = selected - grouped
        if rest:
            specs.append(RowSpec(key="ungrouped", label=UNGROUPED, nm_ids=rest))
        return specs

    buckets: dict[str, set[int]] = {}
    for nm in selected:
        card = cards.get(nm)
        name = (card.subject_name if group_by == "subject" else card.brand) if card else ""
        buckets.setdefault(name, set()).add(nm)
    return [
        RowSpec(key=f"{group_by}:{name}", label=name or UNNAMED, nm_ids=frozenset(members))
        for name, members in buckets.items()
    ]


@dataclass(slots=True)
class _SkuGrid:
    """Every article's facts folded per column and over the whole window."""

    cells: dict[int, list[Facts | None]]
    totals: dict[int, Facts]


def fold_sku_days(
    facts: Mapping[tuple[int, date], Facts], columns: list[tuple[date, date]]
) -> _SkuGrid:
    """Fold the SKU-day facts into each article's columns and window total."""
    day_column = column_of_day(columns)
    grid = _SkuGrid(cells={}, totals={})
    for (nm, day), cell in facts.items():
        position = day_column.get(day)
        if position is None:
            continue
        row = grid.cells.setdefault(nm, [None] * len(columns))
        folded = row[position]
        if folded is None:
            folded = row[position] = Facts()
        merge_days(folded, cell)
        merge_days(grid.totals.setdefault(nm, Facts()), cell)
    return grid


def _fold(grid: _SkuGrid, nm_ids: Iterable[int], width: int) -> tuple[list[Facts | None], Facts]:
    """One row's cells and window total, folded across its articles."""
    cells: list[Facts | None] = [None] * width
    total = Facts()
    for nm in nm_ids:
        for position, cell in enumerate(grid.cells[nm]):
            if cell is None:
                continue
            folded = cells[position]
            if folded is None:
                folded = cells[position] = Facts()
            merge_skus(folded, cell)
        merge_skus(total, grid.totals[nm])
    return cells, total


def _row(
    spec: RowSpec,
    cells: list[Facts | None],
    total: Facts,
    metrics: tuple[str, str | None],
    settled: list[bool],
) -> HeatmapRow:
    """Read the chosen metrics off a folded row.

    A column with no facts for the row reads as nothing — unless WB has settled
    it, in which case the settlement's silence is an answer: no sales, zero
    revenue. Every other metric reads ``None`` off that same empty cell, so the
    substitution only ever speaks for the settlement.
    """
    metric, metric2 = metrics
    card = spec.card
    cells = [
        Facts(finance_known=True) if cell is None and known else cell
        for cell, known in zip(cells, settled, strict=True)
    ]
    units = ["" if c is None else spend_unit(c) for c in cells]
    spends = [metric in SPEND_MONEY, metric2 in SPEND_MONEY]
    return HeatmapRow(
        key=spec.key,
        label=spec.label,
        nm_id=card.nm_id if card else None,
        title=card.title if card else "",
        photo_url=card.photo_url if card else "",
        sku_count=len(spec.nm_ids),
        total=read_metric(metric, total),
        values=[None if c is None else read_metric(metric, c) for c in cells],
        total2=None if metric2 is None else read_metric(metric2, total),
        values2=(
            None
            if metric2 is None
            else [None if c is None else read_metric(metric2, c) for c in cells]
        ),
        units=units if spends[0] else None,
        total_unit=spend_unit(total) if spends[0] else "",
        units2=units if spends[1] else None,
        total_unit2=spend_unit(total) if spends[1] else "",
    )


def build_rows(
    specs: list[RowSpec],
    grid: _SkuGrid,
    *,
    width: int,
    metrics: tuple[str, str | None],
    rank: Mapping[int, int],
    settled: list[bool] | None = None,
) -> tuple[HeatmapRow, list[HeatmapRow]]:
    """Compute every row and the "Total" line, most-ordered row first.

    Args:
        specs: The rows, from :func:`build_row_specs`.
        grid: The folded SKU facts, from :func:`fold_sku_days`.
        width: Number of columns.
        metrics: The primary metric and the optional second one.
        rank: Ordered units per article over the window — the default order,
            "popularity", cheap to know whatever metric is on screen.
        settled: Per column, whether WB has settled any day of it; ``None``
            when no finance metric is on screen.
    """
    known = settled if settled is not None else [False] * width
    rows: list[tuple[int, HeatmapRow]] = []
    seen: set[int] = set()
    for spec in specs:
        present = [nm for nm in spec.nm_ids if nm in grid.cells]
        if not present:
            continue
        seen.update(present)
        live = RowSpec(key=spec.key, label=spec.label, nm_ids=frozenset(present), card=spec.card)
        cells, total = _fold(grid, present, width)
        row = _row(live, cells, total, metrics, known)
        rows.append((sum(rank.get(nm, 0) for nm in present), row))
    rows.sort(key=lambda pair: (-pair[0], pair[1].label, pair[1].key))

    all_skus = RowSpec(key="total", label="Total", nm_ids=frozenset(seen))
    cells, total = _fold(grid, sorted(seen), width)
    return _row(all_skus, cells, total, metrics, known), [row for _, row in rows]
