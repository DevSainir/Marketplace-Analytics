"""Day x traffic-bucket metrics-matrix DTOs (the monitoring table's data).

The matrix mirrors the manager's workbook: for every day of the window there
is one column per traffic bucket (traffic type x display zone),
and one row per metric. ALL values are computed server-side — the frontend
only formats and renders them (strict rule: no calculations in the frontend).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from src.modules.monitoring.constants import MAX_MATRIX_DAYS

#: Traffic buckets, in column order. ``uni_*`` are the unified-bid campaign
#: («Единая ставка») zones — split from search-cluster stats; ``manual_*`` are
#: manual-bid campaigns by their enabled zone (``manual_catalog`` is the
#: CATALOG slice of a search-only campaign: WB's search campaigns also
#: deliver in the catalogue, derived as fullstats - normquery). A unified bid has
#: no catalogue bucket: WB reports only its search slice, so a unified «Каталог»
#: column could only ever be empty and was removed on 2026-10-05. ``cpc_*``
#: are the pay-per-click campaigns («CPC»), which WB bills per click rather
#: than per 1000 views and whose bids therefore cannot be read
#: alongside a CPM campaign's — they get their own traffic-type group, split
#: into the same two zones; ``total`` is the funnel-wide «Общая» column and
#: ``organic`` is «Органика» (overall - advertising).
MATRIX_BUCKETS: tuple[str, ...] = (
    "uni_search",
    "uni_shelves",
    "manual_search",
    "manual_catalog",
    "manual_shelves",
    "cpc_search",
    "cpc_shelves",
    "total",
    "organic",
)

#: The advertising buckets that carry editable input facts (``total`` is a
#: funnel/ad roll-up, ``organic`` a difference).
MATRIX_AD_BUCKETS: tuple[str, ...] = (
    "uni_search",
    "uni_shelves",
    "manual_search",
    "manual_catalog",
    "manual_shelves",
    "cpc_search",
    "cpc_shelves",
)

#: «Доля трафика» is normalized WITHIN a traffic type, so each type
#: sums to 100% on its own: a unified campaign's zones cannot be a share of a
#: manual campaign's views, and a CPC campaign — bought per click — is not
#: comparable to either. Maps a bucket to the type it is normalized against.
_BUCKET_TYPES: tuple[str, ...] = ("uni", "manual", "cpc")


def bucket_traffic_type(bucket: str) -> str:
    """Return the traffic type an ad bucket is normalized within.

    Unknown buckets answer ``"manual"``, which is what the single ``uni``/
    ``manual`` split did before CPC campaigns existed — the fallback only ever
    reaches a bucket outside :data:`MATRIX_AD_BUCKETS`, which carries no share.
    """
    for prefix in _BUCKET_TYPES:
        if bucket.startswith(f"{prefix}_"):
            return prefix
    return "manual"


#: Metric rows, in the workbook's row order. Keys are shared verbatim with the
#: frontend, which maps them to labels/formatting only.
MATRIX_METRIC_KEYS: tuple[str, ...] = (
    "traffic_share",
    "spend",
    "views",
    "ctr",
    # The «Общая» column's ADVERTISING clicks — the numerator of its CTR, whose
    # «Клики» row shows the funnel's clicks instead. Emitted for that column
    # only; the frontend reads it into the CTR hover, never as a row.
    "ad_clicks",
    "cpm",
    "cpc",
    "clicks",
    "carts",
    # The viewed card's OWN share of the campaign's carts/orders — emitted only
    # when it is smaller, i.e. when associated size/colour variants converted.
    # The cells themselves show the campaign's number; the frontend reports the
    # difference as the associated share in the carts/orders hover (read-only).
    "carts_sku",
    "cart_conversion",
    "orders",
    "orders_sku",
    "order_conversion",
    "order_sum",
    "buyout_sum",
    "cost_per_order",
    "cost_per_cart",
    "drr_orders",
    "drr_sales",
    "buyout_percent",
    # Prices & SPP — «Общая»-column only, derived from the price snapshot.
    "seller_price",
    "customer_price",
    "spp",
    # Stock — «Общая»-column only, read-only facts from the stock snapshot.
    "stock_quantity",
    "stock_to_client",
    "stock_from_client",
    # Total stock = quantity + both in-transit legs (derived here, NOT in the frontend).
    "stock_total",
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


class MatrixDayCurrencies(BaseModel):
    """What each money cell of one day column is counted in.

    Two sources, never merged: the order money («Заказы»/«Выкупы» in money) is
    WB's own funnel sum — in the workspace's settlement currency — or, on a day WB
    served none, the order count at the day's price, in the prices' currency.
    The spend is in whatever each campaign is billed in, fixed at its creation,
    so a bucket that folds two campaigns can hold two codes. ``""`` is a source
    that states none (spend harvested before WB's label was recorded).
    """

    orders: str = Field(default="", description="Currency of the day's order money.")
    ads: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Spend currencies per bucket key; «total» is the card's whole day.",
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
    currencies: list[MatrixDayCurrencies] = Field(
        default_factory=list, description="Per day, what its money cells are counted in."
    )


# --------------------------------------------------------------------------- #
# Editable working copy (base inputs)
#
# The matrix is *derived* from a small set of input facts. The base state
# carries exactly those inputs so the frontend can edit them (and derived cells
# recompute server-side). It is the unit of the preview/save flow.
# --------------------------------------------------------------------------- #
class AssocSkuCount(BaseModel):
    """One variant's share of a cell's associative conversions.

    The rows behind the carts/orders hover: ``nm_id`` is the size/colour
    variant WB booked the conversion on — the viewed SKU included, which is
    what makes the listed counts sum to the cell's number.
    """

    nm_id: int = Field(description="WB SKU identifier of the variant.")
    vendor_code: str | None = Field(default=None, description="Seller article code.")
    add_to_cart: int = Field(default=0, description="Carts booked on this variant.")
    orders: int = Field(default=0, description="Orders booked on this variant.")


class MatrixAdSkuBase(BaseModel):
    """The viewed card's own share of an ad bucket's metrics.

    An advertising bucket is the whole campaign; these are the part of it
    booked on the card being viewed. «Общая» and «Органика» are built from
    them — the card's own day, and that day minus what the ads brought — and
    the carts/orders hover reports the rest as the associated share.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0


class MatrixAdBucketBase(BaseModel):
    """The editable input facts of one ``(day, ad-bucket)`` cell.

    Every metric here is the CAMPAIGN's, across all the nm_ids it delivered
    for: an advertising column measures an ad campaign, so its spend, its
    traffic and its conversions are the campaign's own — including the
    conversions WB booked on associated size/colour variants
    (WB's "associated conversions"), which are orders the campaign paid for and
    brought.

    ``order_sum`` is ``None`` for split (unified / dual-placement) campaigns
    whose order revenue cannot be attributed to a single zone — that cell
    renders «—» and is not editable.

    ``sku`` is the viewed card's own share of all of it (see
    :class:`MatrixAdSkuBase`).

    ``assoc_skus`` decomposes the conversion totals per variant for the hover,
    and always sums to them. ``assoc_exact`` reports whether that decomposition
    is fact or estimate: the viewed SKU's own counts always split exactly, but a
    campaign running in two zones has its ASSOCIATED variants' counts
    apportioned between them (WB attributes associated conversions per campaign,
    never per zone) — unless one zone took none of them, where the division is
    forced and the counts are exact again.

    ``campaign_id`` is the WB campaign that delivered the cell — the leading
    one, if two campaigns of one type share it. The frontend links the traffic
    group's header to it. ``None`` where no single campaign is known (a cell
    built by an edit, or a working copy from before the field existed).

    ``currencies`` is what the spend is billed in — one code per campaign
    folded into the cell, ``""`` for one whose label was never recorded.
    """

    campaign_id: int | None = None
    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    currencies: list[str] = Field(default_factory=list)
    sku: MatrixAdSkuBase = Field(default_factory=MatrixAdSkuBase)
    assoc_skus: list[AssocSkuCount] = Field(default_factory=list)
    assoc_exact: bool = True


class MatrixFunnelBase(BaseModel):
    """The editable organic-funnel inputs for one day (the «Общая» column).

    ``seller_price``/``customer_price`` are the day's snapshot prices and are
    editable; «Заказы, ₽» and «СПП» derive from them (read-only). Prices are
    ``None`` (rendered «—», not editable) when no snapshot exists for the day.

    ``has_funnel`` is ``False`` on days WB has not served a funnel row for yet
    (the CURRENT day — prices/stock are snapshotted at harvest time, but the
    funnel always lags a day): the price cells render, while the count cells
    stay blank and read-only (zero counts are not facts there).

    ``order_price`` is what one order was worth that day by WB's own funnel sum
    (``orderSum / orderCount``), in ``order_currency`` — the settlement
    currency, which WB converts to at the Bank of Russia rate of the order day.
    The order money is valued at it, so it pairs with spend billed in the same
    currency without any rate of ours. ``None`` on a day WB served no sum (or no
    orders): the order money then falls back to ``seller_price`` converted by
    ``price_rate`` — the Bank rate of the day, WB's own — into
    ``order_currency``, or, without a rate, stays in ``price_currency``.
    """

    open_count: int = 0
    cart_count: int = 0
    order_count: int = 0
    seller_price: float | None = None
    customer_price: float | None = None
    has_funnel: bool = True
    order_price: float | None = None
    order_currency: str = ""
    price_currency: str = ""
    price_rate: float | None = None


class MatrixStockBase(BaseModel):
    """The day's stock totals (read-only facts, «Общая» column).

    Carried from the nearest stock snapshot (see the matrix builder); never
    editable — stock is a harvested fact, not a derivable input.
    """

    quantity: int = 0
    in_way_to_client: int = 0
    in_way_from_client: int = 0


class MatrixDayBase(BaseModel):
    """All input facts for a single day column.

    ``buckets`` holds only the ad buckets that delivered that day; missing ones
    render «—». ``unclassified`` is the ad remainder (campaigns whose settings
    are unsynced) — hidden and read-only, but summed into «Общая»/«Органика» and
    the traffic-share denominator so those stay faithful.
    ``lagged_buyout_percent`` and ``stock`` are precomputed facts and read-only;
    «Выкупы, ₽» is derived order-date («Заказы, ₽» x «Процент выкупа»).

    ``cell_overrides`` holds DISPLAY overrides for non-invertible cells (a
    derived rollup, the empty «Каталог» zone, a tainted split) keyed by
    ``"<bucket>:<metric>"`` — applied verbatim AFTER the formulas run, so every
    cell is editable without disturbing the dynamic recompute of input cells.
    """

    day: date
    has_advertising: bool = False
    buckets: dict[str, MatrixAdBucketBase] = Field(default_factory=dict)
    unclassified: MatrixAdBucketBase = Field(default_factory=MatrixAdBucketBase)
    funnel: MatrixFunnelBase | None = None
    lagged_buyout_percent: float | None = None
    stock: MatrixStockBase | None = None
    cell_overrides: dict[str, float] = Field(default_factory=dict)


class MatrixBaseState(BaseModel):
    """The full editable working copy for a SKU window (all input facts).

    ``days`` is capped because this shape is a **request** body on preview and
    save, not only a response: the server recomputes every cell of whatever
    working copy it is handed, so an uncapped list is server-side arithmetic a
    caller can ask for by the megabyte. The ceiling is the widest window the
    analysis endpoints will resolve, so no legitimate client can reach it.
    """

    days: list[MatrixDayBase] = Field(default_factory=list, max_length=MAX_MATRIX_DAYS)


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
    failed_sources: list[str] = Field(
        default_factory=list,
        description=(
            "WB sources that did not answer during an otherwise successful "
            "refresh (e.g. 'sales-funnel'). A harvest tolerates a partial WB "
            "outage, so 'successful' alone cannot tell the user why the numbers "
            "did not move."
        ),
    )
    stage: int | None = Field(
        default=None,
        description=(
            "Which stage of the refresh is running: 1 = advertising, funnel, "
            "stocks and prices; 2 = buyout percentages. Stage 1's rows are "
            "already committed when stage 2 begins, so the client may redraw "
            "the table on the transition instead of waiting for the whole run."
        ),
    )
    stages: int | None = Field(
        default=None, description="How many stages this refresh has in total."
    )
    percent: int | None = Field(
        default=None,
        description=(
            "How far along the refresh is, 0-100. Present only while running; "
            "a finished task reports its outcome through 'ready'/'successful'."
        ),
    )
    message: str | None = Field(
        default=None,
        description=(
            "Russian, user-facing description of what is happening right now, "
            "rendered verbatim under the refresh button."
        ),
    )
