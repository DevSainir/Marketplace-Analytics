"""Only the API may connect as the least-privilege role.

`marketplace_app` cannot run DDL and is subject to the row-level policies. That
is right for a request and wrong for everything else in the stack: `migrate`
runs `alembic upgrade head`, `worker` and `beat` harvest across every workspace
with no tenant bound, and the backup's `pg_dump` has to see all of it.

Every service shares one `.env`, so the obvious rollout — point `POSTGRES_USER`
at the new role — switches all of them at once. That would break the next
deploy and the next harvest while appearing to tighten the API. The api services therefore carry
their own `APP_POSTGRES_USER` / `APP_POSTGRES_PASSWORD`, falling through to the
shared value when unset.

This reads the compose file, because the failure it guards is a one-line edit
that looks like a simplification and whose consequence arrives a day later at
03:00 in someone else's job.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_COMPOSE = pathlib.Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yml"

#: The override that switches identity, and the only place it may appear.
_OVERRIDE = "APP_POSTGRES_USER"

#: Services that must keep the owner, and what they would lose without it.
_MUST_STAY_OWNER = {
    "migrate": "runs alembic upgrade head, which is DDL the restricted role is refused",
    "worker": "harvests across every workspace with no tenant bound",
    "beat": "schedules those harvests",
    "postgres": "is the server; POSTGRES_USER there creates the owner role itself",
}


def _services() -> dict[str, Any]:
    """The compose file's services, with YAML anchors already resolved.

    `api_standby` is `<<: *api`, so the merge is what makes its inherited
    environment visible here — the same mechanism compose itself uses.
    """
    return yaml.safe_load(_COMPOSE.read_text())["services"]


def _environment(service: dict[str, Any]) -> dict[str, str]:
    """A service's `environment:` block as a mapping.

    Compose accepts both a mapping and a `KEY=value` list; this file uses the
    mapping form, but a future edit switching styles should not silently make
    every assertion below pass.
    """
    raw = service.get("environment") or {}
    if isinstance(raw, list):
        return dict(item.split("=", 1) for item in raw)
    return {str(k): str(v) for k, v in raw.items()}


def test_the_api_services_can_change_identity() -> None:
    """Both of them — `api_standby` inherits the block and is easy to forget."""
    # Act
    services = _services()

    # Assert
    for name in ("api", "api_standby"):
        user = _environment(services[name]).get("POSTGRES_USER", "")
        assert _OVERRIDE in user, (
            f"{name} cannot connect as the least-privilege role: its POSTGRES_USER "
            f"is {user!r}, which ignores {_OVERRIDE}"
        )


def test_the_api_falls_back_to_the_shared_credentials() -> None:
    """Unset, the override must change nothing — that is what makes it safe to ship."""
    # Act
    environment = _environment(_services()["api"])

    # Assert
    assert environment["POSTGRES_USER"] == "${APP_POSTGRES_USER:-${POSTGRES_USER:-marketplace}}"
    assert environment["POSTGRES_PASSWORD"] == "${APP_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD}}"


def test_no_other_service_can_be_switched_to_it() -> None:
    """The whole point of the override is that it reaches the API and nothing else."""
    # Act
    services = _services()

    # Assert
    for name, why in _MUST_STAY_OWNER.items():
        environment = _environment(services[name])
        assert _OVERRIDE not in "".join(environment.values()), (
            f"{name} would connect as the restricted role, and it {why}"
        )


def test_the_services_this_covers_still_exist() -> None:
    """A guard naming a service that has gone stops guarding anything."""
    # Act
    defined = set(_services())

    # Assert
    assert defined >= set(_MUST_STAY_OWNER) | {"api", "api_standby"}, (
        f"compose no longer defines: {(set(_MUST_STAY_OWNER) | {'api'}) - defined}"
    )
