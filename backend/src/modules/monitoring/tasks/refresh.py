"""The interactive "Refresh" path: one workspace's SKUs, on demand.

Split from :mod:`~src.modules.monitoring.tasks.harvest`, which holds the
harvest ENGINE — the fetch/flatten/persist machinery that both this task and
the nightly ``harvest_all`` drive. The two are different responsibilities and
they fail differently: the engine's concerns are WB's surfaces and one atomic
transaction, and this module's are the things that are true only because a
person is waiting — a tighter time limit than the fleet-wide backstop, no
account-wide sale feed, and a returned ``failed_sources`` the SPA can show.

Keeping them in one file was fine until it was 516 lines, over the repository's
hard ceiling. The seam was already there in the docstrings; this only makes it
a file boundary.
"""

from __future__ import annotations

from datetime import date, timedelta

from celery import Task

from src.core.celery_app import celery_app
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.harvest import harvest_timer, record_harvest_outcome
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.modules.monitoring.repos import ProductCardRepository
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.monitoring.tasks.full_refresh import (
    celery_progress,
    refresh_workspace_data,
)
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)


#: Tighter than the fleet-wide backstop in ``core/celery_app.py``, because this
#: is the one harvest a user can start from the browser and therefore the one
#: that can be started repeatedly.
#:
#: Raised from ten minutes when this task stopped being a subset of the nightly
#: pass and became equal to it: it now pulls the account-wide sale feed and the
#: 22-day buyout-cohort pass, and the cohort pass alone is 22 sequential
#: rate-limited requests measuring ~7 minutes. Twenty-five leaves that room to
#: queue behind a scheduled pass competing for the same WB budget, and still
#: bounds what a burst of clicks can pin down.
#:
#: Two other numbers are downstream of this one and must stay above it: the
#: task-ownership binding in ``services/refresh_tracking.py`` (45 min) and the
#: SPA's poll ceilings in ``frontend/src/modules/monitoring/store.js`` (30 min).
#: A ceiling below this one turns a slow success into a visible failure.
_INTERACTIVE_SOFT_TIME_LIMIT_SECONDS: int = 25 * 60


#: Metric label for the interactive refresh. A constant rather than a literal
#: at each of the three places it is needed, because a label that differs by a
#: character between the timer and the row counter silently produces two
#: unrelated series that each look half-broken.
_HARVEST_SKU_WINDOW = "monitoring.sku_window"


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_sku_window",
    bind=True,
    soft_time_limit=_INTERACTIVE_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_INTERACTIVE_SOFT_TIME_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def harvest_sku_window(
    self: Task[object, object],
    nm_ids: list[int],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, object]:
    """Celery entrypoint: harvest and persist WB stats for a SKU window.

    Harvests funnel + stock for ``nm_ids`` and advertising for the campaigns
    that advertise them, using the credentials of the workspace that **owns**
    the SKUs (resolved via the ``product_card`` registry). Args are
    JSON-serializable (dates as ISO strings) to satisfy Celery's JSON task
    serializer.

    This is the interactive "Refresh" path, and it now refreshes everything
    the nightly pass does — including the account-wide sale feed and the
    buyout-cohort pass. It used to skip both, on the sound reasoning that WB
    serves them account-wide only and charges its harshest limiter for them
    (a 39-second 429 backoff, measured live). The cost was real; what it bought
    was "Buyouts, ₽" and "Buyout rate" standing still behind a green tick
    while the seller watched, which is worse. The cohort pass is claimed per
    workspace, so refreshing six SKUs in a row still costs one pass.

    Args:
        nm_ids: SKU identifiers to harvest funnel + stock for. All must belong
            to one workspace (in practice the refresh endpoint passes one SKU).
        date_from: Optional ISO start date; defaults to a 7-day window (the WB
            funnel-history endpoint rejects windows longer than 7 days).
        date_to: Optional ISO end date; defaults to Moscow *yesterday* (WB does
            not serve current-day statistics).

    Returns:
        The persisted row counts per metric family — including ``sales_rows``
        and ``cohort_rows`` — plus ``failed_sources``: the WB sources that did
        not answer. The refresh-status endpoint serves that list to the SPA,
        which is how "Refresh" can say "WB withheld the funnel" instead of
        silently redrawing the same numbers.

    Raises:
        IntegrationError: If the SKUs are not registered to any workspace, or
            the workspace no longer exists (no credentials to harvest with).
    """
    # WB rejects the current date, so the default window ends yesterday; the
    # funnel-history endpoint caps the window at 7 inclusive days.
    end = date.fromisoformat(date_to) if date_to else moscow_today() - timedelta(days=1)
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=6)
    logger.info("Harvesting SKUs %s for %s..%s", nm_ids, start, end)

    async def _run() -> dict[str, object]:
        async with AsyncSessionLocal() as session:
            workspace_id = await ProductCardRepository(session).get_workspace_of_sku(nm_ids[0])
            if workspace_id is None:
                raise IntegrationError(
                    f"SKU {nm_ids[0]} is not registered to any workspace; "
                    "cannot pick WB credentials for the refresh."
                )
            tokens = await load_workspace_token_bundle(session, workspace_id)
        # Every line this task writes from here on names the seller it is
        # working for. The task itself resolved the workspace from the SKU, so
        # nothing upstream could have bound it — and a harvest that goes wrong
        # goes wrong for one tenant, which is the first thing anybody reading
        # the log needs to know.
        bind_workspace(workspace_id)
        if tokens is None:
            raise IntegrationError(f"Workspace {workspace_id} no longer exists; refresh aborted.")
        with harvest_timer(_HARVEST_SKU_WINDOW):
            outcome = await refresh_workspace_data(
                tokens=tokens,
                nm_ids=nm_ids,
                date_from=start,
                date_to=end,
                progress=celery_progress(self),
            )
        record_harvest_outcome(
            _HARVEST_SKU_WINDOW,
            counts=outcome.counts,
            failed_sources=outcome.failed_sources,
        )
        return {**outcome.counts, "failed_sources": list(outcome.failed_sources)}

    return run_task(_run())
