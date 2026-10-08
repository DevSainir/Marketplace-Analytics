"""The verify job removes the anonymous volumes its service containers leave.

`verify` runs on the production box with postgres and redis as GitHub service
containers. Both images declare a VOLUME, and the runner removes the containers
after the job but not their anonymous volumes. Nothing else on the box prunes
volumes, so they piled up two per run — 628 of them, 22.8 GB — until the disk
filled and the nightly backup failed on 2026-10-07 and 2026-10-08.

The prune is asserted here rather than trusted to review, and so is its one
dangerous spelling: `-a`/`--all` would extend it to NAMED volumes no container
holds, and production's data lives in named volumes.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_WORKFLOW = pathlib.Path(__file__).resolve().parents[4] / ".github" / "workflows" / "tests.yml"


def _verify_commands() -> list[str]:
    jobs: dict[str, Any] = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return [step["run"] for step in jobs["verify"]["steps"] if "run" in step]


def test_verify_prunes_volumes_before_its_checkout() -> None:
    """Before the work: a cancelled run never reaches an "after" step."""
    jobs: dict[str, Any] = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    steps = jobs["verify"]["steps"]
    checkout = next(i for i, s in enumerate(steps) if "actions/checkout" in s.get("uses", ""))

    pruning = [i for i, s in enumerate(steps) if "docker volume prune" in s.get("run", "")]

    assert pruning, "verify no longer prunes the volumes its service containers leave"
    assert pruning[0] < checkout


def test_the_volume_prune_never_reaches_named_volumes() -> None:
    """`-a` would take production's named volumes whenever their container is down."""
    prunes = [
        line
        for command in _verify_commands()
        for line in command.splitlines()
        if "docker volume prune" in line
    ]

    widened = [line for line in prunes if " -a" in line or "--all" in line]

    assert not widened, f"volume prune widened to named volumes: {widened}"
