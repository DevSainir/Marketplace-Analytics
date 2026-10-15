"""The worker's metrics tmpfs must not fill, and must say so before it does.

Written after 2026-10-15. The healthcheck's ``celery inspect ping`` imported the
app every 30 s in multiprocess mode and left a ``counter_<pid>.db`` and a
``histogram_<pid>.db`` behind each time; ``mark_process_dead`` keeps those on
purpose. The 32 MB mount filled in ~40 h, and from 04:01 MSK every process that
touched a metric died with SIGBUS — every task, for three hours. The only page
was ``WorkerKilled``, and its text pointed at memory.

**The healthcheck test runs in a subprocess, and it has to.** Whether metrics
are file-backed is decided once per interpreter, at ``prometheus_client``'s
import (see ``test_metrics_bootstrap.py``), so only a fresh process can show
which files an import leaves.
"""

from __future__ import annotations

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

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _BACKEND_ROOT / "docker" / "Dockerfile"
_ALERTS_FILE = _BACKEND_ROOT / "docker" / "observability" / "alerts.yml"

#: What the healthcheck's ping imports, standing in for the ping itself: the
#: real one needs a broker, and the files are left by the import, not the ping.
_IMPORT_THE_APP = f"{sys.executable} -c 'import src.core.celery_app'"


def _samples(registry: CollectorRegistry) -> dict[str, float]:
    """Flatten a registry's exposition into ``{series name: value}``."""
    return {sample.name: sample.value for metric in registry.collect() for sample in metric.samples}


def _healthcheck_env_prefix() -> str:
    """The shell assignments the Dockerfile's HEALTHCHECK puts before ``celery``."""
    match = re.search(r"HEALTHCHECK[^\n]*\\\n\s*CMD (.*?)celery ", _DOCKERFILE.read_text())
    assert match, "no HEALTHCHECK ... CMD ... celery line in docker/Dockerfile"
    return match.group(1)


def _files_left_by(command: str, multiproc_dir: Path) -> list[str]:
    """Run ``command`` in a shell inside a worker-like environment; list what it left.

    Args:
        command: A shell command line, run from the backend root.
        multiproc_dir: What the container's ``PROMETHEUS_MULTIPROC_DIR`` points at.

    Returns:
        The names of the files in ``multiproc_dir`` once the command has exited.
    """
    env = dict(os.environ)
    env.pop("prometheus_multiproc_dir", None)
    env["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    # S602/S603: the command is this module's constant plus a prefix read from
    # the repo's own Dockerfile — no input a caller controls.
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
    return sorted(path.name for path in multiproc_dir.iterdir())


def test_the_healthcheck_leaves_no_metric_files_behind(tmp_path: Path) -> None:
    """The regression: two files per ping, every 30 s, until the mount was full."""
    # Act
    left = _files_left_by(_healthcheck_env_prefix() + _IMPORT_THE_APP, tmp_path)

    # Assert
    assert left == []


def test_an_import_in_multiprocess_mode_does_leave_files(tmp_path: Path) -> None:
    """The control, so the test above is not passing because nothing ever writes.

    If importing the app stopped creating any metric file, the healthcheck test
    would pass whatever the Dockerfile said.
    """
    # Act
    left = _files_left_by(_IMPORT_THE_APP, tmp_path)

    # Assert
    assert any(name.startswith(("counter_", "histogram_")) for name in left)


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
