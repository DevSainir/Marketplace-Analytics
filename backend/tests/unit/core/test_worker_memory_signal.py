"""The worker's memory, and the death it ends in, must both leave a series.

Without it, prefork children can be OOM-killed repeatedly while Prometheus holds
no evidence of any of them. Two gaps make that possible and both are pinned
here: multiprocess mode drops the default process collector, so the one
container whose working set is driven by data volume would be the one container
publishing no resident set at all; and a killed child's task lands in
``celery_tasks_total{state="failure"}``, where three events in half a day is
0.00007/s against an alert threshold of 0.05.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from celery.exceptions import WorkerLostError
from prometheus_client import CollectorRegistry

from src.core.observability import celery_runtime, collectors
from src.core.observability.celery_runtime import (
    _bind_task_context,
    _record_task_failure,
    _record_task_outcome,
)
from src.core.observability.collectors import (
    CGROUP_MEMORY_LIMIT_SERIES,
    CGROUP_MEMORY_USED_SERIES,
    CgroupMemoryCollector,
)
from src.core.observability.metrics import (
    CELERY_TASK_MEMORY_GROWTH,
    CELERY_TASK_PEAK_MEMORY,
    CELERY_TASK_START_MEMORY,
    CELERY_WORKER_LOST,
)

ALERTS_FILE = Path(__file__).resolve().parents[3] / "docker" / "observability" / "alerts.yml"


@pytest.fixture
def cgroup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the collector at a writable stand-in for ``/sys/fs/cgroup``."""
    monkeypatch.setattr(collectors, "_CGROUP_USAGE", tmp_path / "memory.current")
    monkeypatch.setattr(collectors, "_CGROUP_LIMIT", tmp_path / "memory.max")
    return tmp_path


def _samples(registry: CollectorRegistry) -> dict[str, float]:
    """Flatten a registry's exposition into ``{series name: value}``."""
    return {sample.name: sample.value for metric in registry.collect() for sample in metric.samples}


def test_the_worker_publishes_what_it_is_using_and_what_it_is_allowed(cgroup: Path) -> None:
    """Both halves, because neither one alone says whether there is room left.

    768 MiB is only alarming next to the usage, and 640 MB is only alarming next
    to the ceiling. The alert divides one by the other.
    """
    (cgroup / "memory.current").write_text("279961600\n")
    (cgroup / "memory.max").write_text("805306368\n")
    registry = CollectorRegistry()
    registry.register(CgroupMemoryCollector())

    samples = _samples(registry)

    assert samples[CGROUP_MEMORY_USED_SERIES] == 279961600
    assert samples[CGROUP_MEMORY_LIMIT_SERIES] == 805306368


def test_an_uncapped_cgroup_publishes_no_ceiling(cgroup: Path) -> None:
    """``memory.max`` reads ``max`` when nothing limits the container.

    Exposing that as a number would be a lie in whichever direction it was
    rounded — zero reads as "no memory allowed", and a huge value invents a
    ceiling the kernel does not have. Absent is the honest answer, and it makes
    the alert's ratio silently undefined rather than confidently wrong.
    """
    (cgroup / "memory.current").write_text("279961600\n")
    (cgroup / "memory.max").write_text("max\n")
    registry = CollectorRegistry()
    registry.register(CgroupMemoryCollector())

    samples = _samples(registry)

    assert samples[CGROUP_MEMORY_USED_SERIES] == 279961600
    assert CGROUP_MEMORY_LIMIT_SERIES not in samples


def test_a_host_with_no_cgroup_v2_publishes_nothing_and_does_not_raise(cgroup: Path) -> None:
    """A developer's laptop has neither file, and a scrape there must still work.

    This collector runs inside the same exposition as every other metric. A
    raise here would cost the whole scrape — the module's standing rule is that
    a failed sample costs one gauge and never the scrape.
    """
    registry = CollectorRegistry()
    registry.register(CgroupMemoryCollector())

    samples = _samples(registry)

    assert samples == {}


def test_the_memory_alert_reads_the_series_the_collector_actually_publishes() -> None:
    """These two names are declared by a collector, so no metric scan can check them.

    ``test_alert_rules.py`` validates alert expressions against the metric
    OBJECTS in ``metrics.py``, and a collector defines none — so a typo in
    either name would produce a rule that evaluates to nothing for ever, which
    is the exact failure that file exists to prevent.
    """
    document = yaml.safe_load(ALERTS_FILE.read_text())
    rules = {rule["alert"]: rule for group in document["groups"] for rule in group["rules"]}

    expression = rules["WorkerMemoryNearLimit"]["expr"]

    named = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression))
    assert {name for name in named if "_" in name} == {
        CGROUP_MEMORY_USED_SERIES,
        CGROUP_MEMORY_LIMIT_SERIES,
    }


def test_a_task_that_died_with_its_worker_is_counted_apart_from_one_that_raised() -> None:
    """A killed child is an absence, not a failure, and needs its own series.

    Both are counted as failures — that part is unchanged — but only this one
    means the work was abandoned without unwinding and will not be retried. Left
    inside the general failure rate it is unreachable: the rate alert needs
    0.05/s and this happens three times a day.
    """
    task = type("Task", (), {"name": "finreports.harvest_finance"})()
    before = CELERY_WORKER_LOST.labels(task_name=task.name)._value.get()

    _record_task_failure(sender=task, exception=ValueError("ordinary"))
    _record_task_failure(sender=task, exception=WorkerLostError("signal 9 (SIGKILL)"))

    assert CELERY_WORKER_LOST.labels(task_name=task.name)._value.get() == before + 1


def test_the_worker_registry_carries_the_memory_collector(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    """The exporter renders a registry and calls nothing else.

    The worker has no exposition route, so ``refresh_sampled_metrics`` — which
    is what keeps every other sampled gauge current — never runs there. Being
    registered on the registry is the only way this reading reaches a scrape.
    """
    from src.core.observability import celery_runtime

    (cgroup / "memory.current").write_text("1234\n")
    # The real switch: multiprocess mode is derived from this path being set,
    # never declared separately (`src.core.config.observability`).
    multiproc = cgroup / "multiproc"
    multiproc.mkdir()
    monkeypatch.setattr(celery_runtime.settings, "prometheus_multiproc_dir", str(multiproc))
    # `MultiProcessCollector` reads the directory from the environment rather
    # than from settings — see `prepare_multiprocess_dir`, which exports it for
    # the same reason.
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(multiproc))

    registry: Any = celery_runtime.build_worker_registry()

    assert _samples(registry)[CGROUP_MEMORY_USED_SERIES] == 1234


def _observed(histogram: Any, task_name: str) -> float:
    """The histogram's running sum for one task — its single observation here."""
    return float(histogram.labels(task_name=task_name)._sum.get())


def test_a_task_reports_the_water_line_the_recycler_will_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The metric and `--max-memory-per-child` must read the same number.

    The limit is chosen from this histogram, so a second way of measuring "what
    a child weighs" would be choosing the limit from a figure the recycler does
    not use. Both come from `billiard.compat.mem_rss`, which is why patching it
    here moves both.
    """
    readings = iter([200_000.0, 260_000.0])
    monkeypatch.setattr(celery_runtime, "mem_rss", lambda: next(readings))
    task = type("Task", (), {"name": "guide.capture_daily"})()

    _bind_task_context(task_id="t-1", task=task)
    _record_task_outcome(task_id="t-1", task=task, state="SUCCESS")

    assert _observed(CELERY_TASK_PEAK_MEMORY, task.name) == 260_000.0 * 1024


def test_a_task_is_credited_only_with_the_growth_it_caused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A high-water mark is inherited, so the absolute figure blames the wrong task.

    A cheap task running after an expensive one reports the expensive one's
    number. Without the difference across the task, the histogram would say
    `ab_tests.poll_rotations` needs 525 MB — and the limit would be chosen to
    accommodate a task that allocates nothing.
    """
    readings = iter([500_000.0, 500_000.0])
    monkeypatch.setattr(celery_runtime, "mem_rss", lambda: next(readings))
    task = type("Task", (), {"name": "ab_tests.poll_rotations"})()

    _bind_task_context(task_id="t-2", task=task)
    _record_task_outcome(task_id="t-2", task=task, state="SUCCESS")

    assert _observed(CELERY_TASK_MEMORY_GROWTH, task.name) == 0.0
    assert _observed(CELERY_TASK_PEAK_MEMORY, task.name) == 500_000.0 * 1024


def test_a_platform_that_cannot_report_memory_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero would sit in the lowest bucket and drag the distribution down.

    billiard treats a zero as "unable to determine memory usage" and so does
    this. An absent observation is honest; a fabricated 0 MB task would make the
    histogram argue for a lower limit than the evidence supports.
    """
    monkeypatch.setattr(celery_runtime, "mem_rss", lambda: 0)
    task = type("Task", (), {"name": "monitoring.harvest_all"})()
    before = _observed(CELERY_TASK_PEAK_MEMORY, task.name)

    _bind_task_context(task_id="t-3", task=task)
    _record_task_outcome(task_id="t-3", task=task, state="SUCCESS")

    assert _observed(CELERY_TASK_PEAK_MEMORY, task.name) == before


def test_a_task_records_the_floor_it_started_from_before_it_can_die(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reading a killed task still leaves, and the gap it closes.

    Peak and growth are written at `task_postrun`, so a harvest the kernel kills
    records neither: the surviving runs understate what
    `finreports.harvest_finance` grows by while the cgroup gauge sits at the
    limit, and only the second number is true.

    This one is written before the task body runs, so it survives whatever
    happens next. It cannot say what the task went on to need — nothing inside
    a process that no longer exists can — but it says what it was handed, and
    "this task wants too much" versus "this task was given too little" is the
    distinction the whole diagnosis turned on.
    """
    monkeypatch.setattr(celery_runtime, "mem_rss", lambda: 540_000.0)
    task = type("Task", (), {"name": "finreports.harvest_finance"})()
    before = _observed(CELERY_TASK_START_MEMORY, task.name)

    _bind_task_context(task_id="t-floor", task=task)

    assert _observed(CELERY_TASK_START_MEMORY, task.name) == before + 540_000.0 * 1024


def test_a_platform_that_cannot_report_memory_records_no_floor_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero is "we could not read it", and it must not land in the lowest bucket.

    Same rule as the other two: billiard treats a zero from `mem_rss` as
    "unable to determine memory usage", and a fabricated 0 MB floor would argue
    for a lower limit than the evidence supports.
    """
    monkeypatch.setattr(celery_runtime, "mem_rss", lambda: 0)
    task = type("Task", (), {"name": "guide.capture_monthly"})()
    before = _observed(CELERY_TASK_START_MEMORY, task.name)

    _bind_task_context(task_id="t-floor-none", task=task)

    assert _observed(CELERY_TASK_START_MEMORY, task.name) == before
