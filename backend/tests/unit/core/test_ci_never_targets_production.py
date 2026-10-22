"""Nothing CI runs may address the production stack by default.

The end-to-end tier stands up its own stack and is fenced off through Compose
— its own project name, its own ports, and a guard step that fails the job if
either is lost.

That fence does not cover everything: `scripts/load_seed.sh` does not go through
Compose. It runs `docker exec` against a container **named by a shell default**,
and if that default is `marketplace-analytic-postgres-1` — the production stack's
container — a seed run on a Docker host shared with production truncates the
live `monitoring` schema: harvested history, pinned SKUs and per-day notes.

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
_LOAD_WORKFLOW = _ROOT / ".github" / "workflows" / "load.yml"

#: The production stack's Compose project, and therefore the prefix of every
#: container name that belongs to the live service.
_PRODUCTION_PROJECT = "marketplace-analytic"
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

    A literal here is not a style problem: it is exactly the line that would
    empty production, and it reads as harmless in review precisely because the name
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
    it reads the marker from the *target's* stack, because a CI checkout's own
    `backend/.env` is a copy of `.env.example` and says `local` even when the
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

    assert env["COMPOSE_PROJECT_NAME"] == "marketplace-analytic-e2e"
    assert env["SEED_PG_CONTAINER"].startswith("marketplace-analytic-e2e")
    assert env["SEED_PG_CONTAINER"] != _PRODUCTION_POSTGRES


def _load_job() -> dict[str, Any]:
    """The k6 job, which is the only thing here that generates overload."""
    return dict(yaml.safe_load(_LOAD_WORKFLOW.read_text())["jobs"]["k6"])


def test_the_load_profiles_never_run_on_the_production_box() -> None:
    """The one job in this repository that must never run on a self-hosted runner.

    Moving it onto one is a single-word edit that reads like routine cleanup.
    It is not: `matrix-spike` drives 120 concurrent users and `auth-flood` 60
    requests a second, both deliberately trying to overload what they point at.
    On a host that also serves production that is not a test.

    The workflow also asserts `RUNNER_ENVIRONMENT` at run time — belt and
    braces, because a label is a promise and the environment variable is a
    fact. This is the half that fails in review instead of at 02:00.
    """
    runner = _load_job()["runs-on"]
    labels = [runner] if isinstance(runner, str) else list(runner)

    assert "self-hosted" not in labels, (
        f"the k6 job runs on {labels}. These profiles exist to overload their target; "
        "the self-hosted runner shares two cores with the live API."
    )
    assert "prod-vps" not in labels, labels


def test_the_load_stack_is_a_throwaway_of_its_own() -> None:
    """Same reasoning as the browser tier, and the same failure if it lapses.

    `load_seed.sh` reaches a database by container NAME, outside Compose. The
    load job seeds too, so it needs the same declared target the e2e job needs
    — and it must not be the e2e project either, or two jobs would fight over
    one stack the moment they overlap.
    """
    env = dict(_load_job().get("env") or yaml.safe_load(_LOAD_WORKFLOW.read_text())["env"])

    assert env["COMPOSE_PROJECT_NAME"] == "marketplace-analytic-load"
    assert env["SEED_PG_CONTAINER"].startswith("marketplace-analytic-load")
    assert env["SEED_PG_CONTAINER"] != _PRODUCTION_POSTGRES


def test_the_load_runner_pins_the_binary_it_downloads() -> None:
    """A load runner that fetches `latest` reports changes nobody committed.

    Every action in these workflows is pinned by SHA. k6 arrives as a tarball
    from a release page instead, so the pin is a version plus a checksum, and
    the checksum is the half that makes it a pin rather than a preference.
    """
    env = dict(yaml.safe_load(_LOAD_WORKFLOW.read_text())["env"])

    assert env["K6_VERSION"].startswith("v")
    assert len(env["K6_SHA256"]) == 64, env["K6_SHA256"]

    steps = [step for step in _load_job()["steps"] if "sha256sum" in str(step.get("run", ""))]
    assert steps, "nothing verifies the k6 download; the version pin alone is decoration"
