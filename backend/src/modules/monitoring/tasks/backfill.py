"""Tick tasks that walk a new workspace's monitoring history.

Each task does one bounded step and re-enqueues itself. Nothing here loops to
completion, and that is the point: a backfill runs for hours beside a service
that must keep working, so it has to be interruptible at every step and hold
nothing between them.

Three rules the ticks obey, in the order they matter:

1. **The harvest always wins.** A tick that finds the nightly fleet lock held
   re-enqueues itself further out and returns without calling WB. The backfill
   is the one that gives way — it has hours, and the harvest has a window.
2. **One step, then let go.** ~90 seconds of work, then the worker slot is
   free. A tick never becomes the reason a queue is backed up.
3. **The row is the truth.** Progress and the resume point are the same
   Postgres row, so a redelivered tick, a deploy or a restart costs one step.

The catalogue lane is here too, though it is one request and finishes at once:
it registers ``product_card.workspace_id``, which is what makes every row the
other lanes write provably this tenant's, so it runs first and the others wait
for it.
"""

from __future__ import annotations

import uuid
from collections.abc import Coroutine

from celery import Task

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.tasks import run_task
from src.integrations.wildberries import WBContentClient
from src.modules.monitoring.repos import ProductCardRepository
from src.modules.monitoring.services.backfill import (
    advance_advertising,
    advance_funnel,
    build_ingestion_service,
)
from src.modules.monitoring.services.orders_walk import advance_orders
from src.modules.workspaces.contract import (
    BackfillLane,
    BackfillState,
    LaneStep,
    WorkspaceTokenBundle,
    claim_chain,
    load_workspace_token_bundle,
    read_cursor,
    record_failure,
    record_progress,
)

logger = get_logger(__name__)

#: The fleet harvest's lock. Held while the nightly pass walks every workspace;
#: a tick that sees it steps aside rather than competing for WB's budget.
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"

#: Seconds to wait before the next step of a lane that is making progress.
#: Small: the pacing that matters happens inside the step, against WB's own
#: token bucket. This is only the gap between worker slots.
_NEXT_STEP_SECONDS = 5

#: Seconds to wait when the nightly harvest is running. Longer than the harvest
#: itself takes, so a yielding tick does not spend the whole pass waking up to
#: find the lock still held.
_YIELD_SECONDS = 20 * 60

#: A tick may not run longer than this. Every step is bounded work by
#: construction; the limit is the backstop for a WB call that hangs.
_TICK_SOFT_LIMIT_SECONDS = 5 * 60

_TASK_RETRY_KWARGS = {
    "autoretry_for": (IntegrationError,),
    "retry_backoff": 60,
    "retry_backoff_max": 900,
    "retry_kwargs": {"max_retries": 3},
}


async def _guard[T](lane: BackfillLane, workspace_id: str, body: Coroutine[object, object, T]) -> T:
    """Run a tick body, and make sure a death leaves a trace before it escapes.

    Without this a lane that raises simply stops: the chain's only thread of
    continuation is the re-enqueue at the end of the body it never reached, and
    nothing else in the system is watching. The failure is recorded on the lane
    and on a counter an alert reads, and then re-raised so Celery still sees it.
    """
    try:
        return await body
    except BaseException as error:
        await record_failure(workspace_id=uuid.UUID(workspace_id), lane=lane, error=error)
        raise


async def _harvest_is_running() -> bool:
    """Whether the nightly fleet harvest currently holds its lock.

    A Redis failure answers ``False``: the backfill proceeding while Redis is
    down is a smaller problem than the backfill stalling for good because it
    could not ask.
    """
    try:
        return bool(await get_redis().exists(_HARVEST_LOCK_NAME))
    except Exception:
        logger.warning("Could not read the harvest lock; assuming it is free.")
        return False


async def _load(workspace_id: str) -> WorkspaceTokenBundle:
    """Load one workspace's decrypted tokens, or refuse the tick."""
    async with AsyncSessionLocal() as session:
        tokens = await load_workspace_token_bundle(session, uuid.UUID(workspace_id))
    if tokens is None:
        raise IntegrationError(f"Workspace {workspace_id} no longer exists; backfill aborted.")
    bind_workspace(tokens.workspace_id)
    return tokens


async def _nm_ids(workspace_id: uuid.UUID) -> list[int]:
    """The SKUs registered to this workspace."""
    async with AsyncSessionLocal() as session:
        return await ProductCardRepository(session).list_workspace_nm_ids(workspace_id)


async def _run_step(
    *,
    task_name: str,
    workspace_id: str,
    lane: BackfillLane,
    step: object,
    chain: str,
) -> dict[str, object]:
    """Record a finished step and queue the next one if there is one.

    Args:
        task_name: The registered name of the tick to re-enqueue.
        workspace_id: The workspace, as a string (Celery serializes JSON).
        lane: Which lane reported.
        step: The :class:`LaneStep` the lane returned.
        chain: This chain's token, handed to the next tick so it can tell
            whether it is still the live one.

    Returns:
        A small dict for the task result and the log.
    """
    assert isinstance(step, LaneStep)
    await record_progress(
        workspace_id=uuid.UUID(workspace_id),
        lane=lane,
        state=BackfillState.DONE if step.finished else BackfillState.RUNNING,
        done_units=step.done,
        total_units=step.total,
        cursor=step.cursor,
        message=step.message,
    )
    if not step.finished:
        celery_app.send_task(
            task_name,
            kwargs={"workspace_id": workspace_id, "chain": chain},
            countdown=_NEXT_STEP_SECONDS,
        )
    logger.info(
        "backfill %s for %s: %s/%d, rows=%d, finished=%s",
        lane,
        workspace_id,
        step.done,
        step.total,
        step.rows,
        step.finished,
    )
    return {"lane": str(lane), "done": step.done, "total": step.total, "rows": step.rows}


async def _yield_to_harvest(
    *, task_name: str, workspace_id: str, lane: BackfillLane, chain: str
) -> bool:
    """Step aside if the nightly harvest is running. Returns whether we did."""
    if not await _harvest_is_running():
        return False
    await record_progress(
        workspace_id=uuid.UUID(workspace_id),
        lane=lane,
        message="Ждём ночную загрузку данных…",
    )
    celery_app.send_task(
        task_name,
        kwargs={"workspace_id": workspace_id, "chain": chain},
        countdown=_YIELD_SECONDS,
    )
    logger.info("backfill %s for %s yielded to the nightly harvest.", lane, workspace_id)
    return True


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.backfill_catalogue",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def backfill_catalogue(self: Task[object, object], workspace_id: str) -> dict[str, object]:
    """Register the workspace's cards, then start the lanes that need them.

    One request, so there is no cursor and no second tick. It runs first
    because ``product_card.workspace_id`` is what every other lane's rows are
    proved by — and it starts the funnel and advertising lanes itself, so the
    ordering is expressed once, here, rather than assumed by three callers.
    """

    async def _run() -> dict[str, object]:
        tokens = await _load(workspace_id)
        ws_id = uuid.UUID(workspace_id)
        await record_progress(
            workspace_id=ws_id,
            lane=BackfillLane.CATALOGUE,
            state=BackfillState.RUNNING,
            message="Загружаем карточки товаров…",
        )
        cards = []
        if tokens.content:
            async with WBContentClient(settings, token=tokens.content) as content:
                cards = await content.fetch_all_cards()
            async with AsyncSessionLocal() as session:
                service = build_ingestion_service(session)
                await service.ingest_catalog(cards, workspace_id=ws_id)
                await session.commit()
        await record_progress(
            workspace_id=ws_id,
            lane=BackfillLane.CATALOGUE,
            state=BackfillState.DONE,
            done_units=len(cards),
            total_units=len(cards),
            message=(
                f"Каталог загружен: {len(cards)} SKU."
                if cards
                else "Нет токена «Контент» — используем уже известные SKU."
            ),
        )
        for task_name in (
            "monitoring.backfill_funnel",
            "monitoring.backfill_advertising",
            "monitoring.backfill_orders",
        ):
            celery_app.send_task(task_name, kwargs={"workspace_id": workspace_id})
        return {"cards": len(cards)}

    return run_task(_guard(BackfillLane.CATALOGUE, workspace_id, _run()))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.backfill_funnel",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def backfill_funnel(
    self: Task[object, object], workspace_id: str, chain: str | None = None
) -> dict[str, object]:
    """Walk a few more days of funnel history, then queue the next step.

    Args:
        workspace_id: The workspace being walked.
        chain: The token of the tick chain this one continues. ``None`` starts a
            fresh chain and supersedes any other running on this lane — which is
            what a watchdog restart wants, and what stops the restart from
            walking alongside the tick it was meant to replace.
    """

    async def _run() -> dict[str, object]:
        name = "monitoring.backfill_funnel"
        token = await claim_chain(uuid.UUID(workspace_id), BackfillLane.FUNNEL, chain)
        if token is None:
            logger.info("backfill funnel for %s superseded by a newer chain.", workspace_id)
            return {"superseded": True}
        if await _yield_to_harvest(
            task_name=name, workspace_id=workspace_id, lane=BackfillLane.FUNNEL, chain=token
        ):
            return {"yielded": True}
        tokens = await _load(workspace_id)
        nm_ids = await _nm_ids(tokens.workspace_id)
        if not nm_ids:
            await record_progress(
                workspace_id=tokens.workspace_id,
                lane=BackfillLane.FUNNEL,
                state=BackfillState.DONE,
                message="Нет SKU — воронку собирать не для чего.",
            )
            return {"skipped": True}
        cursor = await read_cursor(workspace_id=tokens.workspace_id, lane=BackfillLane.FUNNEL)
        step = await advance_funnel(tokens, nm_ids=nm_ids, cursor=cursor)
        return await _run_step(
            task_name=name,
            workspace_id=workspace_id,
            lane=BackfillLane.FUNNEL,
            step=step,
            chain=token,
        )

    return run_task(_guard(BackfillLane.FUNNEL, workspace_id, _run()))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.backfill_advertising",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def backfill_advertising(
    self: Task[object, object], workspace_id: str, chain: str | None = None
) -> dict[str, object]:
    """Fetch one 31-day window of advertising history, then queue the next.

    Args:
        workspace_id: The workspace being walked.
        chain: The token of the tick chain this one continues. ``None`` starts a
            fresh chain and supersedes any other running on this lane — which is
            what a watchdog restart wants, and what stops the restart from
            walking alongside the tick it was meant to replace.
    """

    async def _run() -> dict[str, object]:
        name = "monitoring.backfill_advertising"
        token = await claim_chain(uuid.UUID(workspace_id), BackfillLane.ADVERTISING, chain)
        if token is None:
            logger.info("backfill advertising for %s superseded by a newer chain.", workspace_id)
            return {"superseded": True}
        if await _yield_to_harvest(
            task_name=name, workspace_id=workspace_id, lane=BackfillLane.ADVERTISING, chain=token
        ):
            return {"yielded": True}
        tokens = await _load(workspace_id)
        cursor = await read_cursor(workspace_id=tokens.workspace_id, lane=BackfillLane.ADVERTISING)
        step = await advance_advertising(tokens, cursor=cursor)
        return await _run_step(
            task_name=name,
            workspace_id=workspace_id,
            lane=BackfillLane.ADVERTISING,
            step=step,
            chain=token,
        )

    return run_task(_guard(BackfillLane.ADVERTISING, workspace_id, _run()))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.backfill_orders",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def backfill_orders(
    self: Task[object, object], workspace_id: str, chain: str | None = None
) -> dict[str, object]:
    """Fetch one page of the orders feed, then queue the next.

    The lane that reaches further back than any other monitoring surface: the
    funnel answers for a rolling window, while ``supplier/orders`` answers from
    any date, so this is where «Заказы» older than the harvest come from.

    Unlike the funnel and advertising lanes it needs no catalogue: the feed is
    account-wide and its rows carry their own ``nm_id``. A кабинет whose cards
    have not registered yet will simply not SEE these rows until they do —
    every read joins through ``product_card`` — and the data is already stored
    by then.

    Args:
        workspace_id: The workspace being walked.
        chain: The token of the tick chain this one continues. ``None`` starts a
            fresh chain and supersedes any other running on this lane.
    """

    async def _run() -> dict[str, object]:
        name = "monitoring.backfill_orders"
        token = await claim_chain(uuid.UUID(workspace_id), BackfillLane.ORDERS, chain)
        if token is None:
            logger.info("backfill orders for %s superseded by a newer chain.", workspace_id)
            return {"superseded": True}
        if await _yield_to_harvest(
            task_name=name, workspace_id=workspace_id, lane=BackfillLane.ORDERS, chain=token
        ):
            return {"yielded": True}
        tokens = await _load(workspace_id)
        cursor = await read_cursor(workspace_id=tokens.workspace_id, lane=BackfillLane.ORDERS)
        step = await advance_orders(tokens, cursor=cursor)
        return await _run_step(
            task_name=name,
            workspace_id=workspace_id,
            lane=BackfillLane.ORDERS,
            step=step,
            chain=token,
        )

    return run_task(_guard(BackfillLane.ORDERS, workspace_id, _run()))
