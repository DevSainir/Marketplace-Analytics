"""No workflow may trigger on `pull_request` — it can only ever expire red.

Development is trunk-based, so the only pull request this repository sees is
the one Release Please opens. GitHub holds workflow runs for Actions-opened PRs
at `action_required` until a human approves them, and `release` merges that PR
within seconds without waiting. The run is therefore never approved, GitHub
**expires** it when the next push supersedes it or the PR closes, and an expired
run's conclusion is `failure` — zero jobs, and the banner "This run likely
failed because of a workflow file issue", which accuses the YAML rather than the
approval that never came.

Every release cut two of those. Nothing broke — the deploy gates on the `main`
run — which is exactly why it survived: a red check that is known to be
harmless teaches people that a red check is harmless.

Re-adding `pull_request` is a one-line edit that reads like restoring lost
coverage. It restores none: the release PR's contents are tested on `main` in
the merge commit seconds later, before the deploy. A branch is tested by
dispatching `tests` against it, which is what the second assertion keeps
possible.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

_WORKFLOWS = pathlib.Path(__file__).resolve().parents[4] / ".github" / "workflows"

#: `pull_request_target` is the same trap wearing a write token.
_FORBIDDEN = ("pull_request", "pull_request_target")


def _triggers(workflow: pathlib.Path) -> dict[str, Any]:
    """A workflow's `on:` block as a mapping of event name to its filters.

    YAML 1.1 reads a bare `on` as the boolean `True`, which is why the key is
    looked up under both spellings — a rename of the file's quoting style must
    not silently empty this test.
    """
    document = yaml.safe_load(workflow.read_text())
    raw = document.get("on", document.get(True))

    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    return dict(raw or {})


def test_no_workflow_triggers_on_pull_request() -> None:
    """A `pull_request` run here is a run that fails without ever starting."""
    offenders = {
        workflow.name: sorted(set(_triggers(workflow)) & set(_FORBIDDEN))
        for workflow in sorted(_WORKFLOWS.glob("*.yml"))
    }

    named = {name: events for name, events in offenders.items() if events}

    assert not named, (
        f"{named} trigger on a pull request. Every PR in this repository is opened "
        "by GITHUB_TOKEN, so the run is held for an approval that never comes and "
        "expires as a failure. Test the branch with `workflow_dispatch` instead."
    )


def test_the_test_pipeline_can_still_be_aimed_at_a_branch() -> None:
    """Dropping `pull_request` is only safe while dispatch replaces it.

    Without this, removing `workflow_dispatch` would leave a branch with no way
    to run the pipeline at all — and would also break the release merge, which
    dispatches `tests` because a GITHUB_TOKEN merge triggers nothing.
    """
    triggers = _triggers(_WORKFLOWS / "tests.yml")

    assert "workflow_dispatch" in triggers
    assert "push" in triggers
