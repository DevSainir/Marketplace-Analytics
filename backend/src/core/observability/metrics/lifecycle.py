"""Whoever creates multiprocess metric files removes them — armed at the same import.

**Why this exists.** In multiprocess mode every process that imports this
package gets a ``counter_<pid>.db``, a ``histogram_<pid>.db`` and gauge files in
``PROMETHEUS_MULTIPROC_DIR`` — the moment the metric objects are built, before a
single value is recorded. ``prometheus_client`` never deletes the counter and
histogram ones, because a dead prefork child's counts must stay in the sum. So
any OTHER process that imports the app and exits — a healthcheck, a
``docker exec`` script, a shell — left its files for ever. The worker's 32 MB
tmpfs filled that way on 2026-10-15 (two files per ``celery inspect ping``,
every 30 s), and a write to a full tmpfs is SIGBUS: every task died on start for
three hours.

**Armed by the import, not by a caller.** The first version of this sweep was
registered by ``prepare_multiprocess_dir`` in ``celery_app`` — a script that
imported only the metrics never armed it. :func:`arm_exit_sweep` runs at the
top of this package's ``__init__``, before any metric object exists, so
"creates files" and "promises to remove them" cannot be separated by a new
entry point somebody forgets about. ``tests/unit/core/test_worker_metrics_dir.py``
holds every entry point to that.

**Except prefork children.** Their counters are the harvest's. billiard ends a
child with ``os._exit``, so atexit never runs there — and the pid check below
makes that a guarantee rather than a property of billiard: a fork inherits the
registration, not the pid.
"""

from __future__ import annotations

import atexit
import contextlib
import os
from pathlib import Path

#: The process that armed the sweep, or ``None`` when multiprocess mode is off.
_armed_in_pid: int | None = None


def _multiproc_dir() -> str:
    """The directory ``prometheus_client`` writes to, read the way it reads it."""
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR", "").strip()


def arm_exit_sweep() -> None:
    """Register :func:`sweep_own_files` for this process, when files will be written.

    Idempotent per process: a second import of the package does not register a
    second hook.
    """
    global _armed_in_pid
    if not _multiproc_dir() or _armed_in_pid == os.getpid():
        return
    _armed_in_pid = os.getpid()
    atexit.register(sweep_own_files)


def sweep_own_files() -> None:
    """Delete every metric file this process wrote — unless it is a forked child."""
    directory = _multiproc_dir()
    if not directory or os.getpid() != _armed_in_pid:
        return
    # Silenced, and deliberately: this runs while the interpreter is tearing
    # down, where an exception is printed to a stderr nobody is reading and can
    # mask the exit code that IS read — the healthcheck's.
    with contextlib.suppress(Exception):
        for path in Path(directory).glob(f"*_{os.getpid()}.db"):
            path.unlink(missing_ok=True)
