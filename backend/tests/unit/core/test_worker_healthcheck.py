"""The worker's healthcheck restarts a worker that keeps failing it.

Docker never restarts an ``unhealthy`` container, so a worker that keeps failing
its ping runs nothing, the nightly harvest included, until a person restarts it.
``docker/worker_healthcheck.sh``
counts consecutive failures and asks PID 1 to shut down; these tests run that
exact script, with a stand-in ``celery`` on ``PATH`` and a stand-in process in
place of PID 1.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "docker" / "worker_healthcheck.sh"

#: Small, so a test does not need six runs to reach the threshold.
_RESTART_AFTER = 3

#: A ``celery`` that answers the ping as ``$FAKE_PING`` says, and records the
#: metrics directory it was given — present-but-empty is what keeps the ping
#: out of the tmpfs.
_FAKE_CELERY = """#!/bin/sh
echo "multiproc=[${PROMETHEUS_MULTIPROC_DIR-unset}]" >> "$FAKE_LOG"
[ "$FAKE_PING" = ok ]
"""


@pytest.fixture
def worker() -> Iterator[subprocess.Popen[bytes]]:
    """A process standing in for the worker's PID 1."""
    process = subprocess.Popen(["sleep", "60"])  # noqa: S607 — a fixed test stand-in
    yield process
    process.kill()
    process.wait()


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A directory holding the stand-in ``celery``."""
    directory = tmp_path / "bin"
    directory.mkdir()
    celery = directory / "celery"
    celery.write_text(_FAKE_CELERY)
    celery.chmod(0o755)
    return directory


def _check(ping: str, worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path) -> int:
    """Run the healthcheck once; return its exit code."""
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_PING": ping,
        "FAKE_LOG": str(tmp_path / "celery.log"),
        "PROMETHEUS_MULTIPROC_DIR": str(tmp_path / "multiproc"),
        "HEALTHCHECK_STATE_DIR": str(tmp_path / "state"),
        "HEALTHCHECK_TARGET_PID": str(worker.pid),
        "HEALTHCHECK_RESTART_AFTER": str(_RESTART_AFTER),
    }
    # S603/S607: the repo's own script, run by `sh`, with no caller input.
    return subprocess.run(  # noqa: S603
        ["sh", str(_SCRIPT)],  # noqa: S607
        env=env,
        capture_output=True,
        timeout=30,
    ).returncode


def _terminated_by(worker: subprocess.Popen[bytes]) -> int | None:
    """The signal that ended the stand-in, or ``None`` while it lives."""
    try:
        code = worker.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return None
    return -code


def test_a_passing_ping_is_healthy(
    worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path
) -> None:
    # Act
    code = _check("ok", worker, fake_bin, tmp_path)

    # Assert
    assert code == 0
    assert _terminated_by(worker) is None


def test_failures_below_the_threshold_only_report_unhealthy(
    worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path
) -> None:
    """A worker still starting, or a Redis blip, must not be restarted."""
    # Act
    codes = [_check("fail", worker, fake_bin, tmp_path) for _ in range(_RESTART_AFTER - 1)]

    # Assert
    assert codes == [1] * (_RESTART_AFTER - 1)
    assert _terminated_by(worker) is None


def test_consecutive_failures_ask_the_worker_to_shut_down_warmly(
    worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path
) -> None:
    """SIGTERM is Celery's warm shutdown: running tasks finish, then PID 1 exits
    and the restart policy brings up a fresh container."""
    # Act
    for _ in range(_RESTART_AFTER):
        _check("fail", worker, fake_bin, tmp_path)

    # Assert
    assert _terminated_by(worker) == signal.SIGTERM


def test_a_success_resets_the_count(
    worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path
) -> None:
    """Only failures IN A ROW mean the worker is stuck; scattered ones do not."""
    # Act
    for _ in range(_RESTART_AFTER - 1):
        _check("fail", worker, fake_bin, tmp_path)
    _check("ok", worker, fake_bin, tmp_path)
    for _ in range(_RESTART_AFTER - 1):
        _check("fail", worker, fake_bin, tmp_path)

    # Assert
    assert _terminated_by(worker) is None


def test_a_worker_that_ignores_the_warm_shutdown_gets_a_cold_one(
    fake_bin: Path, tmp_path: Path
) -> None:
    """A wedged worker may never finish its warm shutdown; SIGQUIT is Celery's cold one."""
    # Arrange — a stand-in that ignores SIGTERM, as a wedged warm shutdown would.
    stubborn = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 60 & wait"])  # noqa: S607
    try:
        # Act
        for _ in range(_RESTART_AFTER * 2):
            _check("fail", stubborn, fake_bin, tmp_path)

        # Assert
        assert _terminated_by(stubborn) == signal.SIGQUIT
    finally:
        stubborn.kill()
        stubborn.wait()


def test_the_ping_runs_with_the_metrics_directory_emptied(
    worker: subprocess.Popen[bytes], fake_bin: Path, tmp_path: Path
) -> None:
    """Present-but-empty is normalised to absent, so the ping counts in memory and
    writes nothing to the tmpfs — even if the healthcheck timeout SIGKILLs it,
    which would skip the exit sweep."""
    # Act
    _check("ok", worker, fake_bin, tmp_path)

    # Assert
    assert (tmp_path / "celery.log").read_text().strip() == "multiproc=[]"
