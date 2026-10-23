"""Stock-detail response DTOs (summary total + size x warehouse breakdown)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class StockCell(BaseModel):
    """Remaining stock for one size (``chrt_id``) at one warehouse."""

    chrt_id: int = Field(description="WB size characteristic id.")
    tech_size: str | None = Field(
        default=None,
        description="Human size label (WB's item size); None if not yet synced.",
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
        description="Human size label (WB's item size); None if not yet synced.",
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
    """One exact snapshot day's stock breakdown.

    ``stock`` is empty (all zeros, no cells) when no snapshot was captured on
    the requested day — snapshots are never carried onto other days.
    """

    stat_date: date = Field(description="The requested snapshot day.")
    stock: StockDetail


class StockRangeResponse(BaseModel):
    """Every day of the analysis window, oldest first.

    Feeds the "Stock by warehouse" ribbon, which renders one column group per
    day and scrolls sideways through them. EVERY calendar day of the window is
    present, including the ones WB never reported — a missing day is an empty
    breakdown rather than a gap in the list, so the ribbon's columns and the
    days they claim to be cannot drift apart.

    ``days`` may be shorter than the window asked for: the ribbon keeps only the
    most recent ``MAX_STOCK_RANGE_DAYS`` days (see the module's constants for
    why a full breakdown per day cannot be served for a year at a time).
    """

    days: list[StockDayResponse] = Field(
        default_factory=list, description="One entry per day of the window, oldest first."
    )
