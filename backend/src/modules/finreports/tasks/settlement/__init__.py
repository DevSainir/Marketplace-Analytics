"""Walking WB's settlement report — by report, or by span.

The source moved on 2026-09-22. `GET /api/v5/supplier/reportDetailByPeriod` was
announced for shutdown on 15.07.2026 and is gone from WB's documentation;
`POST /api/finance/v1/sales-reports/detailed/{reportId}` and its by-period
sibling `…/detailed` replace it at **one request per minute** each against the
old endpoint's one per ~917 s. See ``docs/finreports/MIGRATION_TO_FINANCE_V1.md``.

Either way a report is BOOKED — its header written — only after all of its rows
have landed, from WB's own list entry; a report WB lists money in and serves no
rows for is not booked at all, and every booked report is checked against WB's
``forPaySum`` (:mod:`reconcile`).

WB serves the same rows two ways, and which one a caller wants is a real choice
rather than a preference:

* :func:`walk_settlement_reports` takes report ids, one per request. A report is
  either complete or it is not, and each is booked the moment it finishes. The
  forward harvest always walks this way — it is fetching the week WB published
  this morning, and atomicity is worth more to it than requests are.
* :func:`walk_settlement_window` takes a span, several reports per request. On
  «Демо» that is ~21 reports to a page against one; the unit becomes the
  window, so a walk that dies part-way books nothing and is re-fetched whole.
  The history backfill walks this way whenever it is owed more than one report.

Both are built on :mod:`page`, which owns everything that was expensive to get
right: the token taken before the session exists, the body parsed as it arrives
rather than decoded whole, and a commit per batch.
"""

from src.modules.finreports.tasks.settlement.page import MAX_RETRIES, _ingest_one_streamed_page
from src.modules.finreports.tasks.settlement.reports import (
    MissingReport,
    SettlementWalk,
    walk_settlement_reports,
)
from src.modules.finreports.tasks.settlement.window import WindowWalk, walk_settlement_window

__all__ = [
    "MAX_RETRIES",
    "MissingReport",
    "SettlementWalk",
    "WindowWalk",
    "_ingest_one_streamed_page",
    "walk_settlement_reports",
    "walk_settlement_window",
]
