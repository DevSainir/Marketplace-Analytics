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
    """Series names in a PromQL expression, minus operators, functions and labels.

    Label selectors and quoted strings are stripped first: a matcher like
    ``{task_name="workspaces.sweep_stalled_backfills"}`` is full of
    underscore-bearing words that are emphatically not metric names, and
    treating them as such makes this test fail on correct rules.
    """
    without_labels = re.sub(r"\{[^}]*\}", "", expr)
    without_strings = re.sub(r"\"[^\"]*\"", "", without_labels)
    tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", without_strings))
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


def test_every_backfill_failure_shape_is_covered() -> None:
    """Four shapes, four rules, and none of them is redundant.

    A lane that dies repeatedly but is always restarted never trips the stall
    alert. A lane that stalls once without ever raising never trips the failure
    alert. A lane being restarted forever without moving looks healthy to both.
    And if the sweep itself stops, the gauge the first three read stops being
    written — so the group goes silent exactly when it matters, which is what
    the fourth rule refuses.
    """
    names = {rule["alert"] for rule in _backfill_rules()}

    assert names == {
        "NewOrgBackfillStalled",
        "NewOrgBackfillRestartLoop",
        "NewOrgBackfillFailing",
        "BackfillWatchdogNotRunning",
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


# --------------------------------------------------------------------------- #
# Patience, measured rather than guessed.
#
# Between 2026-09-13 05:09 and 2026-09-14 11:19 these three rules sent fourteen
# pages and fourteen all-clears about a service that was working. Every one of
# them cleared itself: the backfill loop fired for exactly ten minutes three
# times, the settlement walk for fifty-five minutes four times, and the finance
# harvest simply reported that WB had not published anything that morning.
#
# The numbers below are what those measurements bought. A rule whose `for:`
# drops back under the interval it is supposed to outlast is not a tuning
# choice; it is the pager going off again at four in the morning.
# --------------------------------------------------------------------------- #
_BY_NAME = {rule["alert"]: rule for rule in _rules()}


def _minutes(duration: str) -> int:
    """Parse the `for:` durations this file actually uses."""
    unit = duration[-1]
    value = int(duration[:-1])
    return {"m": value, "h": value * 60}[unit]


def test_the_finance_harvest_is_judged_over_more_than_a_day() -> None:
    """Six hours of silence is a fault for the nightly sweep and a Tuesday here.

    `finreports.finance` runs many times a day against a source WB publishes on
    its own schedule — the settlement report, weekly. Most of those runs write
    nothing and are right to. Any window shorter than a full daily cycle turns
    that into a page.
    """
    expr = _BY_NAME["HarvestProducingNoRows"]["expr"]

    finance_windows = re.findall(r'harvest="finreports\.finance"\}\[(\d+)h\]', expr)

    assert finance_windows, (
        "HarvestProducingNoRows no longer gives finreports.finance a window of its "
        "own. On the shared six-hour window it pages every morning WB has not "
        "published, which it did seven times on 2026-09-14 alone."
    )
    assert all(int(hours) > 24 for hours in finance_windows), finance_windows


def test_the_self_clearing_rules_outlast_what_clears_them() -> None:
    """Both fired, and both were over before anyone could have looked.

    Neither threshold moved — the conditions still mean what they meant. What
    changed is how long they must hold before a person is woken, and the
    numbers come from how long the real firings lasted.
    """
    assert _minutes(_BY_NAME["NewOrgBackfillRestartLoop"]["for"]) >= 60, (
        "the restart-loop rule fired for exactly ten minutes, three times, against "
        "a P&L lane that was walking normally behind WB's 15-minute window."
    )
    assert _minutes(_BY_NAME["SettlementWalkIncomplete"]["for"]) >= 120, (
        "a single partial window is recovered by the next tick — that has been true "
        "since 2026-09-08. Only partials that keep happening need a person."
    )


def test_a_source_muted_in_harvest_partial_is_watched_for_its_return() -> None:
    """Muting a dead source is fine; forgetting it was muted is not.

    `card-prices` fired HarvestPartial every night from 2026-09-22 about a
    captcha nobody can solve from here, so the rule leaves it out. Without a
    rule that notices the storefront answering again, the exclusion would
    outlive the outage and hide the next one.
    """
    muted = re.findall(r'source!="([^"]+)"', _BY_NAME["HarvestPartial"]["expr"])

    watchers = {
        source
        for rule in _rules()
        if rule["alert"] != "HarvestPartial"
        for source in re.findall(r'harvest_partial_total\{[^}]*source="([^"]+)"', rule["expr"])
    }

    assert set(muted) <= watchers, set(muted) - watchers


PROMETHEUS_FILE = ALERTS_FILE.with_name("prometheus.yml")


def test_every_job_a_rule_names_is_one_prometheus_scrapes() -> None:
    """A rule on a job nobody scrapes evaluates to nothing, forever.

    `Watchdog` is the sharp case: it reads Alertmanager's own counters, which
    went unscraped until 2026-09-30 — 210 failed Telegram deliveries out of 213,
    in plain sight of nobody. A rule reading a job that is not in
    prometheus.yml is exactly that again.
    """
    scraped = {
        job["job_name"] for job in yaml.safe_load(PROMETHEUS_FILE.read_text())["scrape_configs"]
    }

    for rule in _rules():
        named = set(re.findall(r'job="([^"]+)"', rule["expr"]))
        assert named <= scraped, f"{rule['alert']} reads unscraped jobs: {sorted(named - scraped)}"


def test_the_watchdog_stops_when_telegram_delivery_fails() -> None:
    """The heartbeat is only worth having if the last hop can silence it."""
    expr = _BY_NAME["Watchdog"]["expr"]

    assert 'alertmanager_notifications_failed_total{integration="telegram"}' in expr
    assert 'up{job="alertmanager"}' in expr
