"""A version is a week of work, and a cancelled run is not a failing one.

Two properties of the CI wiring that no code change can break and every
workflow edit can. Both were defects, both were found the same morning
(2026-09-12), and both look like tidying-up when read as a diff:

* **The release merge is gated.** It used to run on every push, which made the
  version number a push counter — 40 releases in three days, twelve of them in
  six hours, several cut by a `chore:` that changed no behaviour. Removing the
  `if:` would restore that silently: nothing fails, versions simply start
  climbing again.

* **The test pipeline's concurrency key carries the event.** `release` merges
  with GITHUB_TOKEN, which triggers nothing, so it dispatches `tests` by hand —
  and without the event in the key that dispatch landed in the same group as the
  push run already going and cancelled it. Every push ended in a red
  "cancelled" that meant nothing was wrong, which is the precise shape of red
  this repository keeps having to remove (see
  ``test_no_workflow_runs_on_pull_request``).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_WORKFLOWS = pathlib.Path(__file__).resolve().parents[4] / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    """One workflow file as a mapping."""
    return dict(yaml.safe_load((_WORKFLOWS / name).read_text()))


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    """The `on:` block, under either spelling — YAML 1.1 reads bare `on` as True."""
    raw = document.get("on", document.get(True))
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    return dict(raw or {})


def _merge_step(document: dict[str, Any]) -> dict[str, Any]:
    """The step that merges the release PR."""
    steps = document["jobs"]["release"]["steps"]
    found = [step for step in steps if step.get("name") == "Merge the release PR"]
    assert len(found) == 1, "the release merge step has been renamed or removed"
    return dict(found[0])


def test_the_release_merge_runs_on_a_schedule_and_not_on_every_push() -> None:
    """The gate that turns 'somebody pushed' back into 'a week of work'."""
    release = _workflow("release.yml")

    condition = _merge_step(release).get("if", "")

    gate = "the release PR merge must be gated on the schedule (or an explicit "
    gate += f"dispatch); found if: {condition!r}. Without it every push cuts a version."
    assert "schedule" in condition, gate
    assert "workflow_dispatch" in condition, gate
    assert "push" not in condition, (
        f"if: {condition!r} lets a push cut a release again, which is the defect "
        "the schedule replaced."
    )


def test_a_release_is_still_cut_weekly_and_on_demand() -> None:
    """A gate with nothing behind it is a release that never happens.

    The dispatch half matters as much as the cron: it is how a fix that cannot
    wait for Sunday still gets a version.
    """
    triggers = _triggers(_workflow("release.yml"))

    assert "workflow_dispatch" in triggers
    crons = [entry["cron"] for entry in triggers.get("schedule") or []]
    assert crons, "release.yml has no schedule — the weekly cut would never fire"
    assert all(len(cron.split()) == 5 for cron in crons), crons


def test_a_dispatched_test_run_cannot_cancel_a_push_run() -> None:
    """The event belongs in the concurrency key.

    Cancelling is still wanted WITHIN an event — a second push supersedes the
    first. It is the cross-event collision that was pure collateral.
    """
    concurrency = _workflow("tests.yml")["concurrency"]

    assert "github.event_name" in concurrency["group"], (
        f"concurrency group {concurrency['group']!r} does not separate events, so "
        "the release's dispatched run will cancel the push run it overlaps."
    )
    assert concurrency["cancel-in-progress"] is True
