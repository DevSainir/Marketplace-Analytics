"""Every service that builds names the stage it wants.

Compose passes no `--target` when the service does not set one, and Docker then
builds the LAST stage in the Dockerfile. That default is silent, and it changes
meaning whenever someone appends a stage. Append an `e2e` stage to the bottom of
the frontend Dockerfile, and a production `frontend` service that never named a
target begins resolving to it. The result builds, starts and passes a health
check while serving the CI config: plain HTTP, no TLS, and a document root
pointing into the image instead of the release directory the deploy installs.

Nothing else catches this. The image is tagged the same either way, a check that
compares a container against the tag it was created from finds them equal, and
`nginx -t` is happy because the config is valid — just not the one production is
meant to run.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_COMPOSE = pathlib.Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yml"


def _building_services() -> dict[str, Any]:
    """The compose services that build an image rather than pulling one."""
    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    return {name: svc for name, svc in services.items() if isinstance(svc.get("build"), dict)}


def test_no_service_builds_whatever_stage_happens_to_be_last() -> None:
    """An unnamed target is a stage chosen by file order, not by intent."""
    untargeted = sorted(
        name for name, svc in _building_services().items() if not svc["build"].get("target")
    )

    assert not untargeted, (
        f"{untargeted} build the Dockerfile's last stage by default; "
        "appending a stage would silently redirect them."
    )


def test_the_production_frontend_does_not_build_the_e2e_stage() -> None:
    """The stage that serves plain HTTP is for throwaway stacks only.

    Named separately from the rule above because this is the consequence that
    matters: `e2e` carries nginx.ci.conf, which terminates no TLS and reads a
    bundle baked into the image. Serving it from production is an outage that
    reports itself as a healthy deploy.
    """
    frontend = _building_services()["frontend"]

    assert frontend["build"]["target"] == "runtime"
