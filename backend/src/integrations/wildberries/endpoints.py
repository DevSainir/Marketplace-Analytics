"""Turning a WB request path into a bounded metric label.

Lives in its own module because both sides of the WB transport need it and
neither may import the other: :mod:`~src.integrations.wildberries.clients.base`
already imports the rate gate, so the gate cannot import back.

**This is a cardinality control, not a formatting helper.** Two WB paths
interpolate an identifier — ``/api/v3/stocks/{warehouse}`` and the settlement
detail ``sales-reports/detailed/{id}`` — and a report id is a fresh number for
every report we ask for. Used raw as a label, every harvest would add a
permanent Prometheus time series per report, forever: memory that grows with
our history rather than with our size, from a code path no user can see.
Templated, every one of them collapses onto a single series per route, which is
also the only thing anybody would want to graph.

The same reasoning governs the HTTP metrics on the API side, where an
unmatched path is grouped as ``handler="none"`` rather than labelled with the
URL a scanner chose (:mod:`src.core.observability.instrument`). Here the ids
are ours; there they are the caller's, which makes that one the more urgent of
the two and this one the easier to forget.
"""

from __future__ import annotations

import re

#: A path segment that is an identifier rather than a route: an integer id, or
#: a UUID. Anchored on ``/`` at both ends so a version segment like ``/v3`` and
#: a word containing digits are left alone.
_ID_SEGMENT_RE = re.compile(
    r"/(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?=/|$)"
)


#: The Finance surface's realization report, which replaced
#: ``/api/v5/supplier/reportDetailByPeriod`` (announced for shutdown on
#: 15.07.2026, left on 2026-09-22) at fifteen times the rate. See
#: ``docs/finreports/MIGRATION_TO_FINANCE_V1.md``.
SALES_REPORTS_LIST_PATH = "/api/finance/v1/sales-reports/list"

#: Detail rows for ONE report. The ``{id}`` is interpolated, so the raw path is
#: never a metric label — :func:`endpoint_label` collapses it back to this.
SALES_REPORTS_DETAILED_PATH = "/api/finance/v1/sales-reports/detailed/{id}"


#: Detail rows by PERIOD rather than by report. Same payload, and a budget of
#: its own at WB: measured on «Демо» 2026-09-26, a by-period request right
#: after a by-id one answered 200, while a second by-id request two seconds
#: later answered 429 (`x-ratelimit-retry: 58`). So it is paced on a bucket of
#: its own here too. The history backfill uses it for a run of consecutive owed
#: reports, where one request is worth eight to twenty-one by id.
SALES_REPORTS_BY_PERIOD_PATH = "/api/finance/v1/sales-reports/detailed"


def sales_report_detail_path(report_id: int) -> str:
    """The detail path for one report, as sent to WB."""
    return f"/api/finance/v1/sales-reports/detailed/{report_id}"


def endpoint_label(path: str) -> str:
    """Collapse a request path onto the route it belongs to.

    Args:
        path: The path as sent to WB, identifiers and all.

    Returns:
        The path with every identifier segment replaced by ``/{id}``.
    """
    return _ID_SEGMENT_RE.sub("/{id}", path)


__all__ = [
    "SALES_REPORTS_BY_PERIOD_PATH",
    "SALES_REPORTS_DETAILED_PATH",
    "SALES_REPORTS_LIST_PATH",
    "endpoint_label",
    "sales_report_detail_path",
]
