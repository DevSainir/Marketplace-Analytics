"""Stock-detail response DTOs (summary total + size x warehouse breakdown)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class StockCell(BaseModel):
    """Remaining stock for one size (``chrt_id``) at one warehouse."""

    chrt_id: int = Field(description="WB size characteristic id.")
    tech_size: str | None = Field(
        default=None,
        description="Human size label (WB 'Размер вещи'); None if not yet synced.",
    )
    warehouse_name: str
    region_name: str
    quantity: int
    in_way_to_client: int
    in_way_from_client: int


class StockSizeTotal(BaseModel):
    """Per-size stock rolled up across all warehouses."""

    chrt_id: int
    tech_size: str | None = Field(
        default=None,
        description="Human size label (WB 'Размер вещи'); None if not yet synced.",
    )
    quantity: int


class StockDetail(BaseModel):
    """Stock summary plus the full size x warehouse breakdown for a SKU.

    ``total_quantity`` is the "all remaining across all warehouses" figure; the
    ``by_size`` and ``cells`` lists provide the drill-downs.
    """

    total_quantity: int = Field(description="Total remaining across all warehouses.")
    total_in_way_to_client: int = Field(description="Total units in transit to clients.")
    total_in_way_from_client: int = Field(description="Total units in transit back from clients.")
    by_size: list[StockSizeTotal] = Field(
        default_factory=list, description="Per-size totals across warehouses."
    )
    cells: list[StockCell] = Field(
        default_factory=list, description="Per-size, per-warehouse detail."
    )


class StockDayResponse(BaseModel):
    """One exact snapshot day's stock breakdown (the two-day comparison view).

    ``stock`` is empty (all zeros, no cells) when no snapshot was captured on
    the requested day — snapshots are never carried onto other days.
    """

    stat_date: date = Field(description="The requested snapshot day.")
    stock: StockDetail
