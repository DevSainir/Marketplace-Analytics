"""Evening top-up: fill the day's missing customer prices, and nothing else.

A full harvest writes the whole price snapshot once, when it runs. Since
2026-09-22 the customer half of that snapshot comes from the order feed, and
that feed can only answer for a SKU that has already sold *today* — so a morning
harvest finds a fraction of the catalogue and the rest of the day's sales arrive
after it has finished. Measured on the day it shipped: a pass at 11:00 MSK
priced 147 of 359 SKUs against the storefront's 206 of 346 the day before.

This task closes that gap without re-running anything else. Two rules shape it:

* **Prices only.** No funnel, no advertising, no stocks — one WB call per
  workspace, against an endpoint whose bucket is ten requests a minute.
* **Only the gaps.** A SKU that already has a price is never asked about and
  never written; the ``customer_price IS NULL`` guard lives in the UPDATE, so
  a harvest landing mid-pass cannot be overwritten by it.

A day is only fillable while it is still today — the order feed serves the
current price, not a history of it — so this is meant to run in the evening,
before midnight Moscow time.
"""

from __future__ import annotations

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries.factory import build_statistics_client
from src.modules.monitoring.repos import PriceRepository
from src.modules.monitoring.services.ingestion.prices import PriceIngestion
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.workspaces.contract import load_workspace_token_bundles

logger = get_logger(__name__)


async def _top_up() -> dict[str, int]:
    """Top up every workspace's missing customer prices for today.

    Sequential and isolated per workspace, for the same reasons the nightly
    fleet walk is: WB meters per seller account, and one workspace's failure
    must not cost the others their top-up.

    Returns:
        ``{"filled": n, "workspaces": n, "workspaces_failed": n}``.
    """
    day = moscow_today()
    async with AsyncSessionLocal() as session:
        bundles = await load_workspace_token_bundles(session)
    if not bundles:
        logger.warning("No workspaces configured; nothing to top up.")
        return {"filled": 0, "workspaces": 0, "workspaces_failed": 0}

    totals = {"filled": 0, "workspaces": 0, "workspaces_failed": 0}
    for bundle in bundles:
        bind_workspace(bundle.workspace_id)
        try:
            async with AsyncSessionLocal() as session:
                repo = PriceRepository(session)
                missing = await repo.skus_missing_customer_price(
                    workspace_id=bundle.workspace_id, stat_date=day
                )
                if not missing:
                    # Nothing to ask WB about: the cheapest possible pass
                    # for a workspace whose prices are already complete.
                    totals["workspaces"] += 1
                    continue
                if not bundle.statistics:
                    # No "Statistics" scope stored: the same treatment any
                    # missing token gets in the harvest — the source is
                    # skipped, not turned into a failure.
                    totals["workspaces"] += 1
                    continue
                async with build_statistics_client(settings, token=bundle.statistics) as client:
                    orders = await client.fetch_order_prices(changed_since=day)
                filled = await PriceIngestion(repo).fill_missing_from_orders(
                    orders,
                    snapshot_date=day,
                    nm_ids=missing,
                    regions=settings.wb_card_regions,
                )
                await session.commit()
            totals["filled"] += filled
            totals["workspaces"] += 1
        except Exception as exc:  # isolate workspaces from each other
            logger.warning("Customer-price top-up failed for workspace '%s': %s", bundle.name, exc)
            totals["workspaces_failed"] += 1
    logger.info(
        "Customer-price top-up for %s: filled %d across %d workspace(s), %d failed.",
        day,
        totals["filled"],
        totals["workspaces"],
        totals["workspaces_failed"],
    )
    return totals


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.top_up_customer_prices",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def top_up_customer_prices() -> dict[str, int]:
    """Fill today's missing customer prices for every workspace.

    Returns:
        A tally of rows filled and workspaces touched.
    """
    return run_task(_top_up())
