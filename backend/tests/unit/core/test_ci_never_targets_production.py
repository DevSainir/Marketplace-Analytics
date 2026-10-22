"""Nothing CI runs may address the production stack by default.

The end-to-end and load tiers stand up their own stacks and are fenced off
through Compose — their own project names, their own ports, and a guard step
that fails the job if either is lost.

That fence covers only what goes through Compose. On 2026-09-10 a seed script
did not: it ran `docker exec` against a container **named by a shell default**,
the default was the production stack's postgres, and a nightly run on a Docker
host shared with production truncated the live `monitoring` schema. Seeding now
runs as `docker compose exec`, inside the job's own project, so there is no
name left to get wrong — and the first test below keeps it that way.

Asserted here, in the cheapest tier that can see it, because each half is one
careless edit from coming undone: a step that addresses a container by name,
and a workflow that stops saying which project it means.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_TESTS_WORKFLOW = _ROOT / ".github" / "workflows" / "tests.yml"
_LOAD_WORKFLOW = _ROOT / ".github" / "workflows" / "load.yml"

#: The production stack's Compose project.
_PRODUCTION_PROJECT = "marketplace-analytic"

#: A docker command that names its container itself instead of letting Compose
#: resolve it inside the job's project.
_BY_NAME = re.compile(r"\bdocker\s+(exec|cp|stop|rm|kill|restart)\b")


def _run_steps(workflow: pathlib.Path) -> list[str]:
    """Every `run:` script of every job in a workflow."""
    document = yaml.safe_load(workflow.read_text())
    return [
        str(step["run"])
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step
    ]


@pytest.mark.parametrize("workflow", [_TESTS_WORKFLOW, _LOAD_WORKFLOW], ids=lambda p: p.name)
def test_no_step_reaches_a_container_by_name(workflow: pathlib.Path) -> None:
    """Every container a tier touches is resolved by Compose, in its own project.

    `docker compose exec api …` cannot reach another project's container;
    `docker exec <name> …` reaches whatever carries the name — which is how the
    seed found production's database.
    """
    offenders = [script for script in _run_steps(workflow) if _BY_NAME.search(script)]

    assert not offenders, f"{workflow.name} addresses containers by name: {offenders}"


def _end_to_end_job() -> dict[str, Any]:
    """The `end-to-end` job of the tests workflow."""
    document = yaml.safe_load(_TESTS_WORKFLOW.read_text())
    return dict(document["jobs"]["end-to-end"])


def test_the_end_to_end_tier_declares_a_project_of_its_own() -> None:
    """Isolation that is implied is isolation nobody notices losing.

    Every Compose call in the job resolves the project from this variable; left
    unset, it falls back to the base file's `name:` — production's.
    """
    env = dict(_end_to_end_job()["env"])

    assert env["COMPOSE_PROJECT_NAME"] == "marketplace-analytic-e2e"
    assert env["COMPOSE_PROJECT_NAME"] != _PRODUCTION_PROJECT


def _load_job() -> dict[str, Any]:
    """The k6 job, which is the only thing here that generates overload."""
    return dict(yaml.safe_load(_LOAD_WORKFLOW.read_text())["jobs"]["k6"])


def test_the_load_profiles_never_run_on_a_self_hosted_runner() -> None:
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
        "a self-hosted runner shares its machine with whatever else runs there."
    )


def test_the_load_stack_is_a_throwaway_of_its_own() -> None:
    """Same reasoning as the browser tier, and the same failure if it lapses.

    The load job stands up and seeds a stack too, so it needs a declared project
    of its own — and not the e2e one either, or two jobs would fight over one
    stack the moment they overlap.
    """
    env = dict(_load_job().get("env") or yaml.safe_load(_LOAD_WORKFLOW.read_text())["env"])

    assert env["COMPOSE_PROJECT_NAME"] == "marketplace-analytic-load"
    assert env["COMPOSE_PROJECT_NAME"] != _PRODUCTION_PROJECT


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
