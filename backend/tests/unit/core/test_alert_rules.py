"""An alert that names a metric nobody publishes is worse than no alert.

It sits in Prometheus evaluating to nothing, forever, and the dashboard it
belongs to looks covered. That is the same failure the backfill watchdog exists
for, one layer up: silence that is indistinguishable from health.

So the rules that page somebody are checked against the metrics the application
actually defines. The backfill group gets the strictest treatment because it is
the newest and because the incident it was written for produced no signal of any
kind.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from prometheus_client import Counter, Gauge, Histogram

from src.core.observability import metrics as app_metrics

ALERTS_FILE = Path(__file__).resolve().parents[3] / "docker" / "observability" / "alerts.yml"

#: Series Prometheus itself publishes, which no application metric defines.
_BUILT_INS = {"up", "vector", "time", "scrape_duration_seconds"}

#: Suffixes prometheus_client appends to a base metric name on exposition.
_SUFFIXES = ("", "_total", "_sum", "_count", "_bucket", "_created")


def _defined_series() -> set[str]:
    """Every series name the application can actually expose."""
    names: set[str] = set()
    for value in vars(app_metrics).values():
        if isinstance(value, Counter | Gauge | Histogram):
            base = value._name
            names.update(base + suffix for suffix in _SUFFIXES)
    return names


def _rules() -> list[dict[str, Any]]:
    """Every alert rule in the file, flattened across groups."""
    document = yaml.safe_load(ALERTS_FILE.read_text())
    return [rule for group in document["groups"] for rule in group["rules"]]


def _backfill_rules() -> list[dict[str, Any]]:
    document = yaml.safe_load(ALERTS_FILE.read_text())
    return [
        rule
        for group in document["groups"]
        if group["name"] == "backfill"
        for rule in group["rules"]
    ]


def _identifiers(expr: str) -> set[str]:
    """Bare identifiers in a PromQL expression, minus operators and functions."""
    tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr))
    keywords = {
        "by",
        "on",
        "and",
        "or",
        "unless",
        "without",
        "group_left",
        "group_right",
        "sum",
        "rate",
        "increase",
        "count",
        "min",
        "max",
        "avg",
        "clamp_min",
        "histogram_quantile",
        "le",
        "job",
        "status",
        "handler",
        "instance",
        "dependency",
        "control",
        "lane",
        "severity",
        "ignoring",
        "offset",
        "absent",
        "changes",
        "delta",
        "deriv",
        "predict_linear",
        "topk",
    }
    return {token for token in tokens if token not in keywords}


def test_every_backfill_alert_names_a_metric_the_app_publishes() -> None:
    """A typo here is an alarm that can never fire, on the one path with no other signal."""
    defined = _defined_series() | _BUILT_INS

    for rule in _backfill_rules():
        used = _identifiers(rule["expr"])
        # Every identifier that looks like a metric (has an underscore and is
        # not a label we already excluded) must be one we publish.
        unknown = {name for name in used if "_" in name} - defined
        assert not unknown, f"{rule['alert']} references undefined series: {sorted(unknown)}"


def test_the_backfill_alarms_are_all_pages() -> None:
    """A new seller's history silently not arriving is not a look-at-it-later.

    The routing in alertmanager.yml keys off exactly this label: `page` skips
    the grouping delay and goes to Telegram immediately, `warn` is batched.
    """
    rules = _backfill_rules()

    assert rules, "the backfill alert group has disappeared"
    for rule in rules:
        assert rule["labels"]["severity"] == "page", rule["alert"]


def test_the_three_backfill_failure_shapes_are_all_covered() -> None:
    """Stalled, restart-looping and outright failing need different responses.

    A single rule on any one of them leaves a real incident unreported: a lane
    that dies repeatedly but is always restarted never trips a stall alert, and
    a lane that stalls once without ever raising never trips a failure alert.
    """
    names = {rule["alert"] for rule in _backfill_rules()}

    assert names == {
        "NewOrgBackfillStalled",
        "NewOrgBackfillRestartLoop",
        "NewOrgBackfillFailing",
    }


@pytest.mark.parametrize("rule", _rules(), ids=lambda rule: str(rule["alert"]))
def test_every_alert_waits_before_firing_and_says_what_to_do(rule: dict[str, Any]) -> None:
    """The file's own two conventions, enforced rather than trusted.

    `for:` is never zero — an alert that fires on one bad scrape fires on a
    deploy, and an alert that fires on a deploy is one people mute. And every
    rule carries a summary, because the person reading it at 03:00 is not the
    person who wrote it.
    """
    assert rule.get("for"), f"{rule['alert']} has no `for:` — it will fire on a single scrape"
    assert rule["annotations"]["summary"].strip()
