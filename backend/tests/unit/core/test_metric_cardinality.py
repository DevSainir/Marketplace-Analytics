"""Metric labels must be bounded, and one of these bounds is a security control.

A Prometheus series is one time series per unique label combination, held in
memory for as long as it is fresh. So a label whose values are not drawn from a
small closed set is not a monitoring inconvenience — it is unbounded memory
growth in a process running on a 3.8 GB box beside the customer database.

There are two ways this codebase can produce one, and they are different
problems:

task id is a fresh UUID for every report we ask for. Left raw, one nightly
harvest would add a permanent series per workspace per night — memory that
grows with our HISTORY rather than with our size.

**Ids a stranger chooses.** A request to a path with no matching route would
otherwise be labelled with the raw path. That makes `/metrics` grow by one
series per URL a scanner tries, unauthenticated, from the internet. It is a
memory-exhaustion primitive, and grouping unmatched paths is the control that
removes it.

The second is why this file lives in the unit tier rather than being treated as
housekeeping.
"""

from __future__ import annotations

import pytest
from prometheus_client import Gauge
from prometheus_client.metrics import MetricWrapperBase

from src.core.observability import metrics
from src.integrations.wildberries.clients.analytics import WBAnalyticsClient
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.integrations.wildberries.endpoints import endpoint_label


def _defined_metrics() -> dict[str, MetricWrapperBase]:
    """Return the metric OBJECTS the module defines, not the classes it imports.

    ``isinstance`` rather than a name check, and the distinction is not
    pedantry: the first version of these scans walked ``vars(metrics)`` and
    matched on attributes, which picked up the imported ``Gauge`` CLASS and
    reported it as an undeclared gauge. A scan that reports a false positive on
    its first run is one whose next failure gets assumed to be another.
    """
    return {
        name: value for name, value in vars(metrics).items() if isinstance(value, MetricWrapperBase)
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # The one that would grow forever: a fresh UUID per report request.
        (
        ),
        (
        ),
        # Grows with the customer list rather than without bound, which is
        # slower and just as wrong.
        ("/api/v3/stocks/12345", "/api/v3/stocks/{id}"),
    ],
)
def test_an_identifier_in_a_wb_path_is_collapsed(path: str, expected: str) -> None:
    """Every WB path that interpolates an id becomes one series, not many."""
    # Act / Assert
    assert endpoint_label(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/nm-report/detail",
        "/api/v1/supplier/sales",
        "/adv/v2/fullstats",
    ],
)
def test_a_route_with_no_identifier_is_left_exactly_alone(path: str) -> None:
    """The other half of the property, and the one a greedy regex breaks.

    A rule aggressive enough to catch every id will also eat ``/v1`` and
    ``/v2`` — and a metric whose endpoint label reads ``/api/{id}/nm-report``
    has lost the distinction it existed to draw, silently, while still looking
    like a working label.
    """
    # Act / Assert
    assert endpoint_label(path) == path


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (WBAnalyticsClient, "analytics"),
        (WBFinanceClient, "finance"),
        # The two whose derived name would be unreadable, so they name
        # themselves. Pinned because a dashboard and an alert rule are written
        # against these strings.
    ],
)
def test_each_wb_surface_reports_under_a_stable_name(client: type, expected: str) -> None:
    """Surface labels are derived from the class name unless overridden.

    Deriving them means a new WB client is instrumented the moment it exists
    rather than the moment somebody remembers to label it — the failure mode
    of the explicit-only design being a surface that is silently absent from
    every graph.
    """
    # Act / Assert
    assert client.surface() == expected


def test_no_metric_is_labelled_by_tenant() -> None:
    """The rule that keeps this exposition bounded AND keeps it non-sensitive.

    ``workspace_id`` and ``organization_id`` grow with the customer list, so
    either as a label multiplies every series by the number of sellers. But the
    stronger reason is disclosure: ``/metrics`` has no tenancy check, because
    it has no tenant — per-tenant series would put one customer's volumes
    somewhere every other reader of the exposition can see them.

    The per-tenant question is answered by the logs, which carry
    ``workspace_id`` on every line and are reached through the same guards as
    everything else. Metrics answer "is the system healthy"; logs answer "for
    whom".
    """
    # Arrange
    forbidden = {"workspace_id", "organization_id", "user_id", "tenant", "email", "client_ip"}

    # Act
    offenders = {
        name: set(metric._labelnames) & forbidden
        for name, metric in _defined_metrics().items()
        if set(metric._labelnames) & forbidden
    }

    # Assert
    assert offenders == {}, f"tenant-shaped metric labels: {offenders}"


def test_every_gauge_declares_how_it_aggregates_across_processes() -> None:
    """A gauge with no multiprocess mode is wrong in the worker, silently.

    The Celery prefork pool means four processes each hold their own copy. For
    a counter, summing is right and automatic. For a gauge it is usually
    nonsense — four workers each seeing "the queue is 12 long" must not report
    48 — so ``prometheus_client`` requires the choice to be made explicitly,
    and the point of this test is that the choice keeps being made when
    somebody adds the next gauge.
    """
    # Act
    undeclared = [
        name
        for name, metric in _defined_metrics().items()
        if isinstance(metric, Gauge)
        if not getattr(metric, "_multiprocess_mode", None)
    ]

    # Assert
    assert undeclared == [], f"gauges with no multiprocess_mode: {undeclared}"
