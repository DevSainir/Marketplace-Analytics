"""An empty ``PROMETHEUS_MULTIPROC_DIR`` must not arm multiprocess mode.

This file exists because of a defect that passed every test on a developer's
machine and crashed every API container in CI.

``prometheus_client`` decides whether metrics are multiprocess-backed by asking
whether ``PROMETHEUS_MULTIPROC_DIR`` is **present**, not whether it has a value,
and it decides at *its own import* — ``ValueClass = get_value_class()`` is a
module-level assignment. So ``PROMETHEUS_MULTIPROC_DIR=`` — the shape a variable
takes the moment it is listed in `.env.example` with no value, which is how a
reader is meant to see that a setting exists — puts every metric into
multiprocess mode against a path of ``""``.

CI's end-to-end job copies `.env.example` to `.env` verbatim. Locally the
variable is simply absent, so nothing was ever wrong on a laptop.

**Run in a subprocess, and it has to be.** Python caches modules, so an
in-process test would be asserting against whichever import happened to come
first in the test session — it would pass whatever the code did. A subprocess is
the only way to observe a decision that is made once per interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Import the application the way a container does, then report which value
#: class ``prometheus_client`` settled on. ``MutexValue`` is single-process,
#: ``MmapedValue`` is multiprocess.
_PROBE = "import main;from prometheus_client.values import ValueClass;print(ValueClass.__name__)"

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _value_class(multiproc_dir: str | None) -> str:
    """Import the app in a fresh interpreter and report the value class.

    Args:
        multiproc_dir: What to set ``PROMETHEUS_MULTIPROC_DIR`` to, or ``None``
            to leave it unset entirely.

    Returns:
        The name of the ``prometheus_client`` value class.
    """
    env = dict(os.environ)
    env.pop("PROMETHEUS_MULTIPROC_DIR", None)
    env.pop("prometheus_multiproc_dir", None)
    if multiproc_dir is not None:
        env["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir
    # S603 is suppressed on the same terms as the other subprocess call sites in
    # this suite: the executable is this interpreter and the argument is the
    # module constant above, so there is no input for a caller to control.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"importing the application failed with PROMETHEUS_MULTIPROC_DIR="
        f"{multiproc_dir!r}:\n{result.stderr[-2000:]}"
    )
    return result.stdout.strip().splitlines()[-1]


def test_an_empty_multiproc_dir_does_not_arm_multiprocess_mode() -> None:
    """The regression. An empty value must mean the same as no value.

    The failure it guards is not subtle once it happens — the API container
    would not start — but it is invisible until something deploys, because the
    variable only becomes empty-but-present when a `.env` is generated from the
    example file.
    """
    # Act
    value_class = _value_class("")

    # Assert
    assert value_class == "MutexValue"


def test_an_absent_multiproc_dir_is_single_process() -> None:
    """The baseline, so the case above is not passing for the wrong reason."""
    # Act / Assert
    assert _value_class(None) == "MutexValue"


def test_a_real_multiproc_dir_still_arms_multiprocess_mode(tmp_path: Path) -> None:
    """And the fix must not have disarmed the thing it is guarding.

    The worker genuinely needs multiprocess mode: its prefork children are
    separate processes, and the one answering a scrape is not the one that
    counted the harvest. A "fix" that simply always deleted the variable would
    pass both tests above and silently make the worker's exporter report only
    its parent's counters — which are always zero, because the parent runs no
    tasks.
    """
    # Act / Assert
    assert _value_class(str(tmp_path)) == "MmapedValue"


@pytest.mark.parametrize("listing", ["PROMETHEUS_MULTIPROC_DIR="])
def test_the_example_env_does_not_list_it_empty(listing: str) -> None:
    """`.env.example` is copied verbatim by CI, so it is a deployment artefact.

    The code fix above makes an empty value harmless, and this keeps the example
    honest anyway: the two belong together because the trap is invisible until
    it is deployed, and a reader who copies this file should not have to know
    about it.
    """
    # Arrange
    example = (_BACKEND_ROOT / ".env.example").read_text()

    # Act
    offending = [line for line in example.splitlines() if line.strip() == listing]

    # Assert
    assert offending == [], (
        "PROMETHEUS_MULTIPROC_DIR must not be listed with an empty value — "
        "prometheus_client tests for the variable's presence, not its value."
    )
