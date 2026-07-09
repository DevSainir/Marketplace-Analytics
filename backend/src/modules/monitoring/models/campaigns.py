"""Advertising campaign dimension model.

A slowly-changing dimension describing each WB advertising campaign (its type
and lifecycle status), sourced from ``GET /adv/v1/promotion/count``. The
advertising fact table (:class:`AdvertisingStatDaily`) references campaigns by
``campaign_id``; joining this dimension lets the API filter/group by campaign
status (active / paused / completed / ...).

Note:
    WB's ``promotion/count`` endpoint exposes ``type`` and ``status`` codes but
    not campaign names. A human-readable ``name`` would require the content /
    campaign-detail API and can be added to this table later without schema
    churn elsewhere.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class Campaign(Base):
    """WB advertising campaign metadata (type + lifecycle status).

    Attributes:
        campaign_id: WB campaign identifier (``advertId``); primary key.
        type: WB campaign type code (e.g. 8 = automatic, 9 = search+catalog).
        status: Raw WB status code (e.g. 9 = active, 11 = paused, 7 = completed).
        status_label: Normalized status string for filtering (see
            :data:`WB_STATUS_LABELS`): ``active`` / ``paused`` / ``completed`` /
            ``ready`` / ``declined`` / ``deleting`` / ``unknown``.
        synced_at: Timestamp of the last sync from WB.
    """

    __tablename__ = "campaigns"
    __table_args__ = {"schema": _SCHEMA}

    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    status_label: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


#: Maps WB numeric status codes to normalized, filterable labels.
WB_STATUS_LABELS: dict[int, str] = {
    -1: "deleting",
    4: "ready",
    7: "completed",
    8: "declined",
    9: "active",
    11: "paused",
}

#: Maps WB numeric campaign-type codes to human-readable labels.
WB_TYPE_LABELS: dict[int, str] = {
    4: "catalog",
    5: "card",
    6: "search",
    7: "recommendations",
    8: "auto",
    9: "auction",  # unified search + catalog auction campaign
}


def normalize_status(status: int) -> str:
    """Return the normalized label for a raw WB campaign status code."""
    return WB_STATUS_LABELS.get(status, "unknown")


def normalize_type(type_code: int) -> str:
    """Return the human-readable label for a raw WB campaign type code."""
    return WB_TYPE_LABELS.get(type_code, "unknown")
