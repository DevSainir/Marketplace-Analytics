"""Day x traffic-bucket metrics-matrix DTOs (the monitoring table's data).

The matrix mirrors the manager's workbook: for every day of the window there
is one column per traffic bucket («тип получения трафика» x «зона показов»),
and one row per metric. ALL values are computed server-side — the frontend
only formats and renders them (strict rule: no calculations in the frontend).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

#: Traffic buckets, in column order. ``uni_*`` are the unified-bid campaign
#: («Единая ставка») zones — split from search-cluster stats; ``manual_*`` are
#: manual-bid campaigns by their enabled zone; ``uni_catalog`` is a legacy WB
#: zone that no longer exists in the v2 API and stays empty; ``total`` is the
#: funnel-wide «Общая» column and ``organic`` is «Органика» (общая - реклама).
MATRIX_BUCKETS: tuple[str, ...] = (
    "uni_search",
    "uni_shelves",
    "uni_catalog",
    "manual_search",
    "manual_shelves",
    "total",
    "organic",
)

#: The four advertising buckets that carry editable input facts (``total`` is a
#: funnel/ad roll-up, ``organic`` a difference, ``uni_catalog`` always empty).
MATRIX_AD_BUCKETS: tuple[str, ...] = (
    "uni_search",
    "uni_shelves",
    "manual_search",
    "manual_shelves",
)

#: Metric rows, in the workbook's row order. Keys are shared verbatim with the
#: frontend, which maps them to labels/formatting only.
MATRIX_METRIC_KEYS: tuple[str, ...] = (
    "traffic_share",
    "spend",
    "views",
    "ctr",
    "cpm",
    "cpc",
    "clicks",
    "carts",
    "cart_conversion",
    "orders",
    "order_conversion",
    "order_sum",
    "buyout_sum",
    "cost_per_order",
    "cost_per_cart",
    "drr_orders",
    "drr_sales",
    "buyout_percent",
)


class MatrixMetricRow(BaseModel):
    """One metric row of the matrix, with precomputed per-cell values.

    ``values`` is flat and day-major: the cell for day index ``d`` and bucket
    index ``b`` (within :data:`MATRIX_BUCKETS`) lives at
    ``values[d * len(buckets) + b]``. ``None`` renders as «—» (metric not
    defined / not computable for that cell).
    """

    key: str = Field(description="Stable metric identifier (see MATRIX_METRIC_KEYS).")
    values: list[float | None] = Field(
        default_factory=list,
        description="Flat day-major cell values: values[day * len(buckets) + bucket].",
    )


class MetricsMatrixRead(BaseModel):
    """The complete day x bucket metrics matrix for one SKU window."""

    days: list[date] = Field(default_factory=list, description="Window days, oldest first.")
    buckets: list[str] = Field(
        default_factory=lambda: list(MATRIX_BUCKETS),
        description="Bucket keys in column order (see MATRIX_BUCKETS).",
    )
    rows: list[MatrixMetricRow] = Field(
        default_factory=list, description="Metric rows in workbook order."
    )


# --------------------------------------------------------------------------- #
# Editable working copy (base inputs)
#
# The matrix is *derived* from a small set of input facts. The base state
# carries exactly those inputs so the frontend can edit them (and derived cells
# recompute server-side). It is the unit of the preview/save flow.
# --------------------------------------------------------------------------- #
class MatrixAdBucketBase(BaseModel):
    """The editable input facts of one ``(day, ad-bucket)`` cell.

    ``order_sum`` is ``None`` for split (unified / dual-placement) campaigns
    whose order revenue cannot be attributed to a single zone — that cell
    renders «—» and is not editable.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0


class MatrixFunnelBase(BaseModel):
    """The editable organic-funnel inputs for one day (the «Общая» column)."""

    open_count: int = 0
    cart_count: int = 0
    order_count: int = 0
    order_sum: float = 0.0
    buyout_sum: float = 0.0


class MatrixDayBase(BaseModel):
    """All input facts for a single day column.

    ``buckets`` holds only the ad buckets that delivered that day; missing ones
    render «—». ``unclassified`` is the ad remainder (campaigns whose settings
    are unsynced) — hidden and read-only, but summed into «Общая»/«Органика» and
    the traffic-share denominator so those stay faithful. ``lagged_buyout_percent``
    is precomputed (it reads a window outside these days) and is read-only.
    """

    day: date
    has_advertising: bool = False
    buckets: dict[str, MatrixAdBucketBase] = Field(default_factory=dict)
    unclassified: MatrixAdBucketBase = Field(default_factory=MatrixAdBucketBase)
    funnel: MatrixFunnelBase | None = None
    lagged_buyout_percent: float | None = None


class MatrixBaseState(BaseModel):
    """The full editable working copy for a SKU window (all input facts)."""

    days: list[MatrixDayBase] = Field(default_factory=list)


class MatrixCellEdit(BaseModel):
    """A single user edit targeting one matrix cell."""

    day: date
    bucket: str = Field(description="Bucket key (see MATRIX_BUCKETS).")
    metric: str = Field(description="Metric key (see MATRIX_METRIC_KEYS).")
    value: float = Field(description="The new displayed value the user typed.")


class MatrixPreviewRequest(BaseModel):
    """Body of the preview endpoint: the working copy plus one pending edit."""

    base: MatrixBaseState
    edit: MatrixCellEdit


class MatrixPreviewResponse(BaseModel):
    """Result of a preview: the recomputed working copy and display matrix."""

    base: MatrixBaseState
    matrix: MetricsMatrixRead


class MatrixSaveRequest(BaseModel):
    """Body of the save endpoint: the working copy to persist as overrides."""

    base: MatrixBaseState


class RefreshEnqueuedResponse(BaseModel):
    """Result of enqueuing a single-SKU WB refresh (poll ``task_id``)."""

    task_id: str = Field(description="Celery task id to poll for completion.")


class RefreshStatusResponse(BaseModel):
    """Status of a single-SKU refresh task."""

    task_id: str
    status: str = Field(description="Celery state: PENDING/STARTED/SUCCESS/FAILURE/...")
    ready: bool = Field(description="True once the task has finished (success or failure).")
    successful: bool = Field(description="True only when the task finished successfully.")
