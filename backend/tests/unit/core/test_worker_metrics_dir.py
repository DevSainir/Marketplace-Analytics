"""Nothing may fill the worker's metrics tmpfs, and it must say so before anything does.

Written after 2026-10-15. The healthcheck's ``celery inspect ping`` imported the
app every 30 s in multiprocess mode and left a ``counter_<pid>.db`` and a
``histogram_<pid>.db`` behind each time; ``mark_process_dead`` keeps those on
purpose. The 32 MB mount filled in ~40 h, and from 04:01 MSK every process that
touched a metric died with SIGBUS — every task, for three hours. The only page
was ``WorkerKilled``, and its text pointed at memory.

The rule these tests hold, so that nobody has to remember a lifecycle hook:
**a process that is not a prefork child leaves no metric file behind when it
exits**, whatever it imported and however it was started. It is enforced where
the files are created (``metrics/lifecycle.py``), and every way of reaching that
code is checked here rather than the one entry point that happened to leak.

**The import tests run in a subprocess, and they have to.** Whether metrics are
file-backed is decided once per interpreter, at ``prometheus_client``'s import
(see ``test_metrics_bootstrap.py``), so only a fresh process can show which
files an import leaves.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from prometheus_client import CollectorRegistry

from src.core.observability import collectors
from src.core.observability.collectors import (
    METRICS_DIR_SIZE_SERIES,
    METRICS_DIR_USED_SERIES,
    MetricsDirCollector,
)
from src.core.observability.metrics import lifecycle

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_SRC = _BACKEND_ROOT / "src"
_METRICS_PACKAGE = _SRC / "core" / "observability" / "metrics"
_ALERTS_FILE = _BACKEND_ROOT / "docker" / "observability" / "alerts.yml"

#: Every way a process in the worker container comes to hold metric files: the
#: narrowest import that creates them, the Celery app (worker, beat, healthcheck,
#: one-off scripts), and the API's entry module.
_ENTRY_POINTS = ["src.core.observability.metrics", "src.core.celery_app", "main"]

#: ``prometheus_client`` classes whose construction creates an mmap file.
_FILE_BACKED_METRICS = {"Counter", "Gauge", "Histogram", "Summary", "Info", "Enum"}

#: Prints the directory listing while the process is still alive, then exits —
#: so one run shows both that files were made and what the exit left.
_LIST_WHILE_ALIVE = "import os,sys;print(len(os.listdir(os.environ['PROMETHEUS_MULTIPROC_DIR'])))"


def _samples(registry: CollectorRegistry) -> dict[str, float]:
    """Flatten a registry's exposition into ``{series name: value}``."""
    return {sample.name: sample.value for metric in registry.collect() for sample in metric.samples}


def _run(command: str, multiproc_dir: Path) -> str:
    """Run ``command`` in a shell inside a worker-like environment.

    Args:
        command: A shell command line, run from the backend root.
        multiproc_dir: What the container's ``PROMETHEUS_MULTIPROC_DIR`` points at.

    Returns:
        The command's stdout.
    """
    env = dict(os.environ)
    env.pop("prometheus_multiproc_dir", None)
    env["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    # S602: the command is built from this module's constants and the repo's
    # own Dockerfile — no input a caller controls.
    result = subprocess.run(  # noqa: S602
        command,
        shell=True,
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def _import_then_list(module: str) -> str:
    """A shell command importing ``module`` and printing the live file count."""
    return f'{sys.executable} -c "import {module};{_LIST_WHILE_ALIVE}"'


@pytest.mark.parametrize("module", _ENTRY_POINTS)
def test_a_process_that_imports_the_app_leaves_no_metric_file_behind(
    module: str, tmp_path: Path
) -> None:
    """The rule itself, for every entry point: files while alive, none after exit."""
    # Act
    alive = int(_run(_import_then_list(module), tmp_path).strip().splitlines()[-1])

    # Assert
    assert alive > 0, "the import made no files, so this test would pass whatever the code did"
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_repeated_runs_do_not_accumulate(tmp_path: Path) -> None:
    """The shape of the outage: one process every 30 s, adding up until SIGBUS."""
    # Act
    for _ in range(3):
        _run(_import_then_list("src.core.celery_app"), tmp_path)

    # Assert
    assert list(tmp_path.iterdir()) == []


def test_a_forked_child_keeps_its_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A prefork child's counters are the harvest's; recycling it must not lose them.

    billiard ends children with ``os._exit``, so the hook does not run there at
    all; this pins the second guarantee, for a fork that does run it.
    """
    # Arrange
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_armed_in_pid", os.getpid() + 1)
    mine = tmp_path / f"counter_{os.getpid()}.db"
    mine.write_text("")

    # Act
    lifecycle.sweep_own_files()

    # Assert
    assert mine.exists()


def test_the_sweep_removes_only_the_files_of_the_process_running_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every kind of its own file — and not a neighbour's that shares a digit."""
    # Arrange
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_armed_in_pid", os.getpid())
    pid = os.getpid()
    mine = [f"counter_{pid}.db", f"histogram_{pid}.db", f"gauge_livesum_{pid}.db"]
    others = [f"counter_1{pid}.db", "histogram_999999.db"]
    for name in mine + others:
        (tmp_path / name).write_text("")

    # Act
    lifecycle.sweep_own_files()

    # Assert
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(others)


def test_only_the_metrics_package_constructs_file_backed_metrics() -> None:
    """The sweep is armed by importing ``metrics``; a metric built elsewhere would
    make files that nothing promised to remove."""
    # Arrange
    offenders = []
    for path in _SRC.rglob("*.py"):
        if _METRICS_PACKAGE in path.parents:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("prometheus_client")
                and {alias.name for alias in node.names} & _FILE_BACKED_METRICS
            ):
                offenders.append(str(path.relative_to(_BACKEND_ROOT)))

    # Assert
    assert offenders == [], "define metrics in src/core/observability/metrics/"


def test_the_worker_publishes_how_full_its_metrics_mount_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves, because the alert divides one by the other."""
    # Arrange
    monkeypatch.setattr(collectors.settings, "prometheus_multiproc_dir", str(tmp_path))
    registry = CollectorRegistry()
    registry.register(MetricsDirCollector())

    # Act
    samples = _samples(registry)

    # Assert
    assert samples[METRICS_DIR_SIZE_SERIES] > 0
    assert 0 <= samples[METRICS_DIR_USED_SERIES] <= samples[METRICS_DIR_SIZE_SERIES]


@pytest.mark.parametrize("directory", ["", "/no/such/metrics/dir"])
def test_a_process_with_no_metrics_mount_publishes_nothing_and_does_not_raise(
    directory: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API and a laptop have no such mount; their scrape must still work."""
    # Arrange
    monkeypatch.setattr(collectors.settings, "prometheus_multiproc_dir", directory)
    registry = CollectorRegistry()
    registry.register(MetricsDirCollector())

    # Act / Assert
    assert _samples(registry) == {}


def test_the_mount_alert_reads_the_series_the_collector_actually_publishes() -> None:
    """A collector declares no metric object, so the alert-rule scan cannot check it."""
    # Arrange
    document = yaml.safe_load(_ALERTS_FILE.read_text())
    rules = {rule["alert"]: rule for group in document["groups"] for rule in group["rules"]}

    # Act
    named = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", rules["WorkerMetricsDirFilling"]["expr"]))

    # Assert
    assert {name for name in named if "_" in name} == {
        METRICS_DIR_USED_SERIES,
        METRICS_DIR_SIZE_SERIES,
    }
