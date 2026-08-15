"""«Поиск по кластерам» response DTOs — both halves scoped to ONE SKU.

The feature lives at the bottom of a SKU's monitoring page, so both answers are
about that SKU:

* :class:`SkuClustersResponse` — the search clusters this SKU's ads served in
  over the page's window. Stored history from ``POST /adv/v1/normquery/stats``;
  covers only phrases the seller paid to appear for. Always shown.
* :class:`SkuSearchPositionResponse` — where this SKU ranks in WB's public
  search for a phrase the user types, checked live. It cannot be recomputed for
  a past day, which is why it is a search box and not a column.

They are deliberately separate types: one is a month of paid impressions, the
other a sample taken seconds ago from a personalized, regional result page.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from src.modules.monitoring.models.pinned_keywords import KEYWORD_MAX_LENGTH
from src.modules.monitoring.schemas.summary import MetricWindow


class ClusterDayStat(BaseModel):
    """One day of a cluster's window (the trend behind a row)."""

    stat_date: date
    views: int
    clicks: int
    orders: int
    spend: float


class SkuClusterItem(BaseModel):
    """One search cluster's advertising totals for this SKU over the window.

    ``avg_position`` is the impression-weighted average AD position inside the
    cluster and is ``None`` when WB reported no position — which is not the same
    as ranking last, so it must never render as 0.
    """

    cluster: str = Field(description="Normalized search phrase WB grouped queries under.")
    views: int
    clicks: int
    add_to_cart: int = Field(description="Add-to-cart events (WB `atbs`).")
    orders: int
    spend: float
    ctr: float = Field(description="clicks / views * 100 (%).")
    cpc: float = Field(description="spend / clicks (rubles).")
    cpm: float = Field(description="spend / views * 1000 (rubles).")
    avg_position: float | None = Field(
        default=None, description="Impression-weighted average ad position; None = unreported."
    )
    days_count: int = Field(description="Days in the window with impressions.")
    campaign_count: int = Field(description="Distinct campaigns that served the cluster.")
    daily: list[ClusterDayStat] = Field(
        default_factory=list,
        description="Per-day totals; every day of the window, zero-filled where WB reported none.",
    )


class SkuClustersResponse(BaseModel):
    """The SKU's search clusters over the window, most impressions first."""

    nm_id: int
    window: MetricWindow
    items: list[SkuClusterItem] = Field(default_factory=list)


class PinnedKeywordItem(BaseModel):
    """One pinned phrase and the last position recorded for it.

    Three states the card must keep apart, because two of them look identical if
    collapsed and mean opposite things to someone deciding on a bid:

    * ``checked_at is None`` — pinned, never probed. The card shows «—».
    * ``checked_at`` set, ``position is None`` — WB answered and the SKU was not
      inside ``positions_scanned``. It may still rank deeper (``truncated``).
    * ``position`` set — a real rank, as of ``checked_at``.
    """

    keyword: str = Field(description="The phrase as the seller pinned it.")
    normalized_query: str | None = Field(
        default=None, description="WB's normalization from the last probe, if any."
    )
    position: int | None = Field(default=None, description="Last known 1-based rank.")
    positions_scanned: int = Field(default=0, description="Depth of the last scan.")
    total_found: int = Field(default=0, description="WB's result count at the last check.")
    truncated: bool = Field(
        default=False, description="WB had results deeper than the last scan reached."
    )
    checked_at: datetime | None = Field(
        default=None, description="When it was last probed; None = never."
    )
    created_at: datetime = Field(description="When the phrase was pinned.")


class PinnedKeywordsResponse(BaseModel):
    """A SKU's pinned phrases, in pin order."""

    nm_id: int
    items: list[PinnedKeywordItem] = Field(default_factory=list)


class PinKeywordRequest(BaseModel):
    """The phrase to pin («Закрепить»)."""

    keyword: str = Field(min_length=1, max_length=KEYWORD_MAX_LENGTH)


class PositionRefreshAccepted(BaseModel):
    """Acknowledgement that a «Проверить все позиции» run was queued.

    Carries the Celery task id so the UI can poll the shared refresh-status
    endpoint, and the pin count so it can say how much work was actually queued
    (zero pins is a legitimate, silent no-op otherwise).
    """

    task_id: str
    pinned_count: int = Field(description="Pins the run will probe for this workspace.")


class OtherSkuPosition(BaseModel):
    """Another SKU of the workspace found in the same scan of the results."""

    nm_id: int
    vendor_code: str | None = Field(default=None, description="Seller article code.")
    position: int = Field(description="1-based rank across the scanned pages.")


class SkuSearchPositionResponse(BaseModel):
    """Where ONE SKU ranks in WB's public search for a typed phrase, right now.

    ``position`` is ``None`` when the SKU was not inside ``positions_scanned`` —
    which means "not in the depth we looked at", not "absent from WB". The depth
    and ``truncated`` are reported so the UI can say which.

    ``other_skus`` costs nothing: the scan reads whole result pages, so the
    workspace's other SKUs that appear in them are already known, and a seller
    comparing their own cards for one phrase is exactly who is looking.
    """

    nm_id: int
    query: str = Field(description="The phrase as typed (trimmed).")
    normalized_query: str | None = Field(
        default=None,
        description=(
            "WB's own normalization of the phrase (`metadata.normquery`) — the same form the "
            "advertising clusters above are keyed by, so it is what links the two halves."
        ),
    )
    checked_at: datetime = Field(description="When the probe ran (UTC); the result is live.")
    total_found: int = Field(description="Products WB reports for the phrase in total.")
    positions_scanned: int = Field(description="Result slots examined (the probe's depth).")
    truncated: bool = Field(
        description="True when WB has more results than the probe scanned, so an unfound SKU "
        "may still rank deeper."
    )
    position: int | None = Field(default=None, description="1-based rank, or None if not found.")
    page: int | None = Field(default=None, description="Result page it was found on.")
    position_on_page: int | None = Field(default=None, description="1-based rank within the page.")
    other_skus: list[OtherSkuPosition] = Field(
        default_factory=list,
        description="The workspace's OTHER SKUs found in the same scan, best first.",
    )
