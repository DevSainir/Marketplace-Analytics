"""Pydantic DTOs for the heatmap: the grid, the catalogue behind its filters, the groups.

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
    # Воронка — WB's sales funnel, one row per SKU per day.
    "orders",
    "order_sum",
    "opens",
    "carts",
    "cart_conversion",
    "order_conversion",
    "organic_opens",
    # Реклама — the Promotion API's per-SKU statistics.
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
    # Цены и остатки — daily snapshots.
    "seller_price",
    "customer_price",
    "spp",
    "stock",
    # Финансы — WB's settlement, which arrives weekly.
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
    """One row: an article, a category, a brand, a group — or the «Итого» line.

    ``values`` runs parallel to :attr:`HeatmapResponse.columns`; ``None`` is a
    cell with nothing to show (not measured, not settled yet, or a ratio with
    no denominator), which the page renders as «—» and leaves unpainted.
    """

    key: str
    label: str
    #: Set on an article row only.
    nm_id: int | None = None
    title: str = ""
    photo_url: str = ""
    #: How many articles the row covers — 1 for an article row.
    sku_count: int
    #: The primary metric over the whole window («Итого» column).
    total: float | None
    values: list[float | None]
    #: The second metric, when one was asked for.
    total2: float | None = None
    values2: list[float | None] | None = None


class HeatmapResponse(BaseModel):
    """The whole grid for one window, one or two metrics, one cut."""

    date_from: date
    date_to: date
    period: Period
    group_by: GroupBy
    metric: MetricKey
    metric2: MetricKey | None
    #: The settlement currency the finance metrics are in; ``""`` when unknown.
    currency: str
    #: Last day WB has settled for this кабинет. Finance cells after it are
    #: ``None`` — WB has not calculated them — rather than zero.
    settled_to: date | None
    #: Newest first, the way the grid reads.
    columns: list[HeatmapColumn]
    #: «Итого» — every article of the selection, counted once.
    totals: HeatmapRow
    #: Most-ordered first; the page re-sorts on a header click.
    rows: list[HeatmapRow]


class HeatmapCatalogItem(BaseModel):
    """One card of the кабинет — a filter option and a group member candidate."""

    nm_id: int
    vendor_code: str
    title: str
    photo_url: str
    subject_name: str
    brand: str


class HeatmapCatalogResponse(BaseModel):
    """The кабинет's catalogue, for the «Категории» and «Артикулы» filters."""

    items: list[HeatmapCatalogItem]
    #: Distinct non-blank subjects, alphabetical.
    subjects: list[str]


class SkuGroupRead(BaseModel):
    """A seller-defined set of articles, shown as one «Группы» option."""

    id: uuid.UUID
    name: str
    nm_ids: list[int]


class SkuGroupList(BaseModel):
    """Every group of the кабинет, by name."""

    items: list[SkuGroupRead]


class SkuGroupWrite(BaseModel):
    """Body of a group create or edit: the whole group, replaced at once."""

    name: GroupName
    #: Bounded: a group is a hand-picked set, and the list is stored row per
    #: article. Each id must be one of the кабинет's own cards.
    nm_ids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1, max_length=500)
