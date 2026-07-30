"""A cohort pass that WB never answered must fail, not log a quiet zero.

On 2026-07-30 the 07:00 MSK pass ran for over an hour, was refused every one of
its 22 days per workspace, and finished by logging «Refreshed 0 cohort days» at
INFO with a green task. «Процент выкупа» is the only figure those calls feed, so
the metric stopped maturing behind a successful-looking schedule. Zero served
days is an outage and has to be reported as one.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import TracebackType
from typing import Self

import pytest

from src.core.exceptions import IntegrationError
from src.modules.monitoring.tasks.cohorts import _refresh_workspace_cohorts
from src.modules.workspaces.contract import WorkspaceTokenBundle


class RefusingAnalyticsClient:
    """An analytics client that refuses every cohort day, as WB did that morning."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept the real client's construction signature and count calls."""
        self.calls = 0

    async def __aenter__(self) -> Self:
        """Enter the async context like the real client."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Leave the context; nothing to close."""
        return

    async def fetch_funnel_cohort_day(self, *, day: date) -> list[object]:
        """Refuse the day the way an exhausted WB bucket does."""
        self.calls += 1
        raise IntegrationError(
            "WildBerries API error 429 on /api/analytics/v3/sales-funnel/products."
        )


def _tokens(*, analytics: str = "analytics-token") -> WorkspaceTokenBundle:
    """Build a token bundle with the analytics scope the pass needs."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(),
        name="Демо",
        analytics=analytics,
    )


async def test_a_pass_that_wb_never_answered_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every day refused is an outage; the task must fail so it gets retried."""
    client = RefusingAnalyticsClient()
    monkeypatch.setattr(
        "src.modules.monitoring.tasks.cohorts.WBAnalyticsClient",
        lambda *args, **kwargs: client,
    )

    with pytest.raises(IntegrationError, match="cohort days"):
        await _refresh_workspace_cohorts(_tokens(), 3)

    assert client.calls == 3


async def test_a_workspace_without_an_analytics_token_is_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace that never configured the scope is not an outage.

    Failing here would turn one unconfigured tenant into a nightly alert for
    everyone else's healthy pass.
    """
    monkeypatch.setattr(
        "src.modules.monitoring.tasks.cohorts.WBAnalyticsClient",
        lambda *args, **kwargs: RefusingAnalyticsClient(),
    )

    refreshed = await _refresh_workspace_cohorts(_tokens(analytics=""), 3)

    assert refreshed == 0
