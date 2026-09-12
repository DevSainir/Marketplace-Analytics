"""The resilience tier must run, and nothing may quietly gate it again.

`tests/performance/resilience` guards pool exhaustion, reclaimed transactions
and write races — eleven tests, about four and a half seconds. It spent months
in a job of its own behind `if: inputs.run_slow_tiers`, a flag the nightly
schedule does not set, so across the 200 most recent workflow runs it executed
zero times. Every one of those runs reported the tier as `skipped`, which in
the Actions UI is indistinguishable from "not needed today".

That is the failure this file refuses: not a red build, but a green one with a
hole in it. The tier now runs inside `verify`, which has no `if:` at all, and
the assertions below are about WHERE it runs rather than what it finds.

They deliberately do NOT pin the runner. Moving jobs between the VPS and hosted
runners is a live question here — hosted minutes ran out, and the tiers are
expected to move again — so a test that froze `runs-on` would be a test that
has to be edited every time the plan changes, which is how a test stops being
read.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_TESTS_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[4] / ".github" / "workflows" / "tests.yml"
)


def _jobs() -> dict[str, Any]:
    """Every job in the test workflow."""
    return dict(yaml.safe_load(_TESTS_WORKFLOW.read_text())["jobs"])


def _steps_running(fragment: str) -> list[tuple[str, dict[str, Any]]]:
    """Every (job id, step) whose `run:` mentions `fragment`."""
    return [
        (job_id, step)
        for job_id, job in _jobs().items()
        for step in job.get("steps", [])
        if fragment in str(step.get("run", ""))
    ]


def test_the_resilience_tier_is_invoked_somewhere() -> None:
    """A tier no workflow names is a tier that does not exist."""
    invocations = _steps_running("tests/performance")

    runners = [step for _, step in invocations if "pytest" in str(step.get("run"))]
    assert runners, (
        "no job runs `pytest tests/performance`. The resilience tier is the only "
        "coverage for connection-pool exhaustion and write races."
    )


def test_the_job_that_runs_it_is_not_behind_a_flag() -> None:
    """The exact shape of the old defect: present, wired, and never reached."""
    invocations = _steps_running("tests/performance")
    jobs = _jobs()

    ungated = [
        job_id
        for job_id, step in invocations
        if "pytest" in str(step.get("run")) and not jobs[job_id].get("if") and not step.get("if")
    ]

    assert ungated, (
        "every job running the resilience tier is behind an `if:`. That is how it "
        "went 200 runs without executing once — `run_slow_tiers` is not set by the "
        "nightly schedule, so `skipped` was the only outcome it ever had."
    )


def test_it_runs_after_the_integration_tier_that_builds_its_database() -> None:
    """Order is not cosmetic here — the wrong one turns the tier into a skip.

    The tier's conftest points at `marketplace_test`, the throwaway database the
    integration tier creates, and SKIPS with a setup hint when it is missing.
    Running it first would therefore be green and empty.
    """
    for job_id, step in _steps_running("tests/performance"):
        if "pytest" not in str(step.get("run")):
            continue
        steps = _jobs()[job_id]["steps"]
        names = [str(s.get("run", "")) for s in steps]
        resilience_at = names.index(str(step.get("run")))
        integration_at = next(
            (i for i, run in enumerate(names) if "pytest tests/integration" in run), None
        )
        assert integration_at is not None, f"{job_id} runs the resilience tier without integration"
        assert integration_at < resilience_at, (
            f"in {job_id} the resilience tier runs before the integration tier, so "
            "`marketplace_test` does not exist yet and every test skips."
        )
