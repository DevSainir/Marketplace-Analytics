"""Pydantic DTOs for the heatmap: the grid, the catalogue behind its filters, groups, norms.

The metric keys are shared verbatim with the frontend, which maps them to
labels, units and the direction the colour runs in — the same split the
monitoring matrix uses. Every VALUE is computed here; the page only formats it
and decides how loudly to paint it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, StringConstraints

#: Every metric the heatmap can paint, grouped the way the picker lists them.
MetricKey = Literal[
    # "Funnel" — WB's sales funnel, one row per SKU per day.
    "orders",
    "order_sum",
    "opens",
    "carts",
    "cart_conversion",
    "order_conversion",
    "organic_opens",
    # "Advertising" — the Promotion API's per-SKU statistics.
    "spend",
    "ad_views",
    "ad_clicks",
    "ctr",
    "cpc",
    "cpm",
    "ad_orders",
    "ad_cr",
    "cpo",
    "drr_orders",
    # "Prices and stock" — daily snapshots.
    "seller_price",
    "customer_price",
    "spp",
    "stock",
    # "Finance" — WB's settlement, which arrives weekly.
    "revenue",
    "sales",
    "profit",
    "margin",
]
METRIC_KEYS: tuple[str, ...] = get_args(MetricKey)

#: How the columns are cut: one per day, per Monday-to-Sunday week, per month.
Period = Literal["day", "week", "month"]

#: What one row stands for.
GroupBy = Literal["sku", "subject", "brand", "group"]

#: A group's name as the seller types it: trimmed, never blank.
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class HeatmapColumn(BaseModel):
    """One column of the grid — a day, or the days of a week or month inside the window."""

    start: date
    end: date


class HeatmapRow(BaseModel):
    """One row: an article, a category, a brand, a group — or the "Total" line.

    ``values`` runs parallel to :attr:`HeatmapResponse.columns`; ``None`` is a
    cell with nothing to show (not measured, not settled yet, or a ratio with
    no denominator), which the page renders as "—" and leaves unpainted.
    """

    key: str
    label: str
    #: Set on an article row only.
    nm_id: int | None = None
    title: str = ""
    photo_url: str = ""
    #: How many articles the row covers — 1 for an article row.
    sku_count: int
    #: The primary metric over the whole window ("Total" column).
    total: float | None
    values: list[float | None]
    #: The second metric, when one was asked for.
    total2: float | None = None
    values2: list[float | None] | None = None
    #: Per cell, the currency of a SPEND metric (spend, CPC, CPM, CPO) — each
    #: cell in its own campaigns' currency, parallel to ``values``/``values2``.
    #: ``None`` for any other metric: its currency is the grid's.
    units: list[str] | None = None
    total_unit: str = ""
    units2: list[str] | None = None
    total_unit2: str = ""


class HeatmapResponse(BaseModel):
    """The whole grid for one window, one or two metrics, one cut."""

    date_from: date
    date_to: date
    period: Period
    group_by: GroupBy
    metric: MetricKey
    metric2: MetricKey | None
    #: The settlement's currency — revenue and profit are in it. ``""`` before
    #: the first report.
    currency: str
    #: The currency WB states for the prices — both prices are in it. NOT the
    #: settlement's: one workspace settles in KGS and is priced in RUB. ``""``
    #: until a price snapshot has recorded it.
    price_currency: str = ""
    #: The currencies the advertising account billed in over the window. Each
    #: spend cell names its own in :attr:`HeatmapRow.units`; a cell over two
    #: currencies has no figure (on one workspace, RUB until 20.08.2026, KGS after).
    ad_currencies: list[str] = Field(default_factory=list)
    #: What "Orders" (the money) is in — WB's funnel sums, the settlement currency.
    order_currency: str = ""
    #: Last day WB has settled for this workspace. Finance cells after it are
    #: ``None`` — WB has not calculated them — rather than zero.
    settled_to: date | None
    #: Oldest first: the grid reads left to right in time, like the monitoring
    #: matrix, and opens scrolled to its newest end.
    columns: list[HeatmapColumn]
    #: "Total" — every article of the selection, counted once.
    totals: HeatmapRow
    #: Most-ordered first; the page re-sorts on a header click.
    rows: list[HeatmapRow]


class HeatmapCatalogItem(BaseModel):
    """One card of the workspace — a filter option and a group member candidate."""

    nm_id: int
    vendor_code: str
    title: str
    photo_url: str
    subject_name: str
    brand: str
    #: Ordered units over the requested window — what the pickers sort by.
    orders: int = 0


class HeatmapCatalogResponse(BaseModel):
    """The workspace's catalogue, for the "Categories" and "SKUs" filters.

    Items come most-ordered first over the requested window.
    """

    items: list[HeatmapCatalogItem]
    #: Distinct non-blank subjects, alphabetical.
    subjects: list[str]


class SkuGroupRead(BaseModel):
    """A seller-defined set of articles, shown as one "Groups" option."""

    id: uuid.UUID
    name: str
    nm_ids: list[int]


class SkuGroupList(BaseModel):
    """Every group of the workspace, by name."""

    items: list[SkuGroupRead]


class SkuGroupWrite(BaseModel):
    """Body of a group create or edit: the whole group, replaced at once."""

    name: GroupName
    #: Bounded: a group is a hand-picked set, and the list is stored row per
    #: article. Each id must be one of the workspace's own cards.
    nm_ids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1, max_length=500)


#: Largest norm magnitude accepted: far past any real day of any metric, and a
#: bound on what a caller can store.
NORM_LIMIT = 1e12


class SkuNormRead(BaseModel):
    """A seller's own norm for one article on one metric, per day."""

    nm_id: int
    metric: MetricKey
    value: float


class SkuNormList(BaseModel):
    """Every norm the workspace has set."""

    items: list[SkuNormRead]


class SkuNormWrite(BaseModel):
    """Body of a norm set: the value, in the metric's own unit, per day."""

    #: Finite and bounded; negative allowed — a profit norm can be a loss.
    value: float = Field(ge=-NORM_LIMIT, le=NORM_LIMIT, allow_inf_nan=False)
