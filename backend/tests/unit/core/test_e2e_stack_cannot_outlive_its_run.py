"""The throwaway end-to-end stack must die when its run dies.

If the nightly browser tier shares a host with a live stack, it can take that
stack down without a single bug in any code this repository tests.

The stack is started under its own Compose project, and `tests.yml` tears it
down in a step marked `if: always()`. But `always()` binds the *workflow*, not
the machine: when the host runs out of memory mid-tier the runner loses
communication with GitHub and no further step executes at all. An overlay that
inherits `restart: unless-stopped` from the base file then makes Docker do
exactly what it was told and bring the throwaway stack back up on every boot —
1.5 GB of test containers beside the live service on a small host with no swap.
A service capped below its true working set is OOM-killed and restarted in a
loop until nothing on the host can be scheduled.

Both halves are one-line properties of the overlay, so they are asserted here
rather than trusted to review: a stack that cannot restart itself cannot
outlive the run that started it, and a budget that fits leaves the live stack
its working set even while the tier is running.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_DOCKER = pathlib.Path(__file__).resolve().parents[3] / "docker"
_BASE = _DOCKER / "docker-compose.yml"
_E2E = _DOCKER / "docker-compose.e2e.yml"

# The tier is sized for a small swapless host it may share with the live stack.
# The live stack and the observability overlay together declare 3424 MB of
# limits, so on a 4 GB host what is left for a throwaway topology is under
# 500 MB of true headroom — which is why this ceiling is a budget rather than a
# guess. It is set at the
# topology's present total; raising it is a decision about the host, not a
# detail of a test, and should be made with `free -m` in hand.
_E2E_MEMORY_CEILING_MB = 1472


def _services(path: pathlib.Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8"))["services"])


def _mem_limit_mb(value: str) -> int:
    """Compose sizes as this repository writes them — always `<n>m`."""
    assert value.endswith("m"), f"unexpected mem_limit format: {value!r}"
    return int(value[:-1])


def test_no_e2e_service_can_restart_itself() -> None:
    """`unless-stopped` is right for a live stack and catastrophic for this one."""
    restarting = sorted(
        name for name, svc in _services(_E2E).items() if (svc or {}).get("restart") != "no"
    )

    assert not restarting, (
        f'{restarting} do not pin `restart: "no"` in the e2e overlay and so '
        "inherit the base file's `unless-stopped`. A throwaway stack that "
        "restarts itself survives the run, the runner and the next reboot."
    )


def test_every_base_service_is_pinned_by_the_overlay() -> None:
    """A service added to the base file inherits its restart policy silently."""
    unpinned = sorted(set(_services(_BASE)) - set(_services(_E2E)))

    assert not unpinned, (
        f"{unpinned} exist in the base stack but are absent from the e2e "
        "overlay, so the e2e run gets production's restart policy and sizing "
        'for them. Add them to the overlay with `restart: "no"` and a cap.'
    )


def test_the_e2e_topology_fits_beside_the_live_stack() -> None:
    """The comment in the overlay once said ~1 GB while the real total was 1536."""
    limits = {
        name: _mem_limit_mb(svc["mem_limit"])
        for name, svc in _services(_E2E).items()
        if (svc or {}).get("mem_limit")
    }
    total = sum(limits.values())

    assert total <= _E2E_MEMORY_CEILING_MB, (
        f"the e2e topology declares {total} MB ({limits}), over the "
        f"{_E2E_MEMORY_CEILING_MB} MB budget it shares the box with production "
        "under. Oversubscribing a swapless host does not degrade it, it wedges it."
    )
