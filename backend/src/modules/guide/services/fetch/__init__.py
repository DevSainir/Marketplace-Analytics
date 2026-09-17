"""One walk per captured feed, split by the shape WB serves it in.

:mod:`feeds` holds the streams, snapshots and take/skip pages; :mod:`reports`
holds the date-windowed ones; :mod:`common` holds what both are handed and what
both give back. The names below are the package's public surface — the
catalogue in :mod:`src.modules.guide.sources` imports from here, never from the
files behind it.
"""

from __future__ import annotations

from src.modules.guide.services.fetch.common import (
    CaptureBatch,
    CapturedRow,
    CaptureWindow,
    as_rows,
    parse_day,
    windows,
)
from src.modules.guide.services.fetch.feeds import (
    fetch_claims,
    fetch_documents,
    fetch_feedbacks,
    fetch_orders,
    fetch_questions,
)
from src.modules.guide.services.fetch.reports import (
    fetch_acceptance_report,
    fetch_goods_return,
    fetch_region_sale,
    fetch_tariffs_pallet,
    fetch_tariffs_return,
)

__all__ = [
    "CaptureBatch",
    "CaptureWindow",
    "CapturedRow",
    "as_rows",
    "fetch_acceptance_report",
    "fetch_claims",
    "fetch_documents",
    "fetch_feedbacks",
    "fetch_goods_return",
    "fetch_orders",
    "fetch_questions",
    "fetch_region_sale",
    "fetch_tariffs_pallet",
    "fetch_tariffs_return",
    "parse_day",
    "windows",
]
