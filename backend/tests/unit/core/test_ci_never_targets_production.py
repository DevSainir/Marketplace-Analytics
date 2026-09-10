"""Nothing CI runs on the production box may address production by default.

The pipeline runs on a self-hosted runner **on the production VPS**. The
end-to-end tier stands up its own stack there and is fenced off through Compose
— its own project name, its own ports, and a guard step that fails the job if
either is lost.

On 2026-09-10 that fence held perfectly and production's `monitoring` schema was
truncated anyway: `scripts/load_seed.sh` does not go through Compose. It runs
`docker exec` against a container **named by a shell default**, and the default
was `marketplace-service-postgres-1` — production's. Seven weeks of harvested
history, every pinned SKU and every per-day note went with it (P2.9 in
docs/security/HARDENING.md).

Both halves of the fix are asserted here, in the cheapest tier that can see
them, because both are one careless edit from coming undone: a default that
names production, and a workflow that stops saying what it means to hit.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPTS = _ROOT / "backend" / "scripts"
_TESTS_WORKFLOW = _ROOT / ".github" / "workflows" / "tests.yml"

#: The production stack's Compose project, and therefore the prefix of every
#: container name that belongs to the live service.
_PRODUCTION_PROJECT = "marketplace-service"
_PRODUCTION_POSTGRES = f"{_PRODUCTION_PROJECT}-postgres-1"

#: The scripts that reach a database by container name rather than through
#: Compose. Both are destructive in one direction or the other: `load_seed`
#: truncates the target, `dump_seed` copies the target into a committed fixture.
_CONTAINER_SCRIPTS = ("load_seed.sh", "dump_seed.sh")


def _default_expression(script: pathlib.Path) -> str:
    """The right-hand side of the script's `CONTAINER=` assignment."""
    for line in script.read_text().splitlines():
        if line.startswith("CONTAINER="):
            return line
    raise AssertionError(f"{script.name} no longer assigns CONTAINER at all.")


def test_no_seed_script_defaults_to_the_production_database() -> None:
    """The fallback must be derived from the project, never spelled out.

    A literal here is not a style problem: it is the exact line that emptied
    production, and it reads as harmless in review precisely because the name
    looks like a local development container. It is the same name.
    """
    offenders = {
        name: _default_expression(_SCRIPTS / name)
        for name in _CONTAINER_SCRIPTS
        if _PRODUCTION_POSTGRES in _default_expression(_SCRIPTS / name)
    }

    assert not offenders, (
        f"{offenders} default to production's database container. Derive the name from "
        "COMPOSE_PROJECT_NAME so an isolated stack addresses its own postgres."
    )


def test_the_loader_refuses_a_production_target() -> None:
    """The backstop under the derivation: recognise production and stop.

    The derivation fixes the caller that exists. This is for the next one — and
    it reads the marker from the *target's* stack, because the runner's own
    `backend/.env` is a copy of `.env.example` and says `local` while the
    container it addresses is production's.
    """
    body = (_SCRIPTS / "load_seed.sh").read_text()

    assert "ENVIRONMENT=" in body
    assert '"production"' in body


def _end_to_end_job() -> dict[str, Any]:
    """The `end-to-end` job of the tests workflow."""
    document = yaml.safe_load(_TESTS_WORKFLOW.read_text())
    return dict(document["jobs"]["end-to-end"])


def test_the_end_to_end_tier_names_the_database_it_seeds() -> None:
    """Isolation that is implied is isolation nobody notices losing.

    The job already declares its Compose project and its ports. The seed target
    is the one thing Compose does not resolve, so it is declared alongside them
    and checked here — a job env that goes quiet again would put the choice back
    where it was: in a shell default, three files away.
    """
    env = dict(_end_to_end_job()["env"])

    assert env["COMPOSE_PROJECT_NAME"] == "marketplace-e2e"
    assert env["SEED_PG_CONTAINER"].startswith("marketplace-e2e")
    assert env["SEED_PG_CONTAINER"] != _PRODUCTION_POSTGRES
