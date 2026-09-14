"""Whose hole this tick goes and fills.

The half :mod:`.gaps` deliberately is not. Detection is one SQL query per
workspace and runs across the fleet every tick; repair is a fortnight-wide walk
on a surface that serves one request per quarter of an hour, paid per workspace
in sequence under a fleet-wide lock. Knowing is cheap, walking is not, and
putting the two in one module is how the ration came to be written twice.

What this adds to the nightly rotation is *when*. The rotation takes one
workspace a night, so a seller short a settlement week could be told about it
four nights before anything went and fetched it — while the report was
fetchable the whole time. An hourly tick repairs instead of waiting its turn,
under the two bounds below.
"""

from __future__ import annotations

import uuid
from datetime import date

from redis.exceptions import RedisError

from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.modules.finreports.constants import (
    GAP_REPAIR_COOLDOWN_PREFIX,
    GAP_REPAIR_COOLDOWN_SECONDS,
)
from src.modules.finreports.tasks.spans import reconciliation_slice
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def gap_repair_due(
    bundles: list[WorkspaceTokenBundle],
    *,
    today: date,
    gaps: dict[uuid.UUID, list[date]],
) -> set[uuid.UUID]:
    """The one workspace this hourly tick repairs a known hole for, if any.

    The hourly pass used to be forward-only and hand every hole to the nightly
    rotation, which takes one workspace a night: a seller short a settlement week
    waited up to five nights while a detector that had already found it said so
    every night. The report was fetchable the whole time.

    So a visible hole is walked within the hour instead. Two bounds keep that
    affordable, and both are the reason this is a function rather than a
    condition inlined above:

    * **One workspace a tick**, chosen by the same rationing the nightly pass
      uses — a lookback walk is three windows of *waiting* on a surface that
      serves one request per quarter of an hour, and the workspaces are walked
      in sequence under a fleet-wide lock.
    * **A cooldown per workspace**, because a hole WB will never serve stays
      visible forever. Without it every tick would spend a fortnight-wide walk
      on the same unfixable day, for good. See
      :data:`~src.modules.finreports.constants.GAP_REPAIR_COOLDOWN_SECONDS`.

    The cooldown is claimed with ``SET NX``, so two runs racing cannot both take
    the same workspace's turn, and it expires on its own — nothing has to clean
    up after a run that dies mid-walk.

    Args:
        bundles: Every workspace this run may look at.
        today: Today in Moscow time.
        gaps: Uncovered days per workspace, from the survey.

    Returns:
        At most one workspace id. Empty when nothing is holed, when the chosen
        workspace is still inside its cooldown, or when Redis cannot answer —
        a repair nobody can ration is one this pass declines to start.
    """
    holed = [bundle for bundle in bundles if gaps.get(bundle.workspace_id)]
    if not holed:
        return set()
    chosen = reconciliation_slice(holed, today=today, gaps=gaps)
    if not chosen:
        return set()
    workspace_id = chosen[0].workspace_id
    key = f"{GAP_REPAIR_COOLDOWN_PREFIX}{workspace_id}"
    try:
        claimed = await get_redis().set(key, "1", nx=True, ex=GAP_REPAIR_COOLDOWN_SECONDS)
    except RedisError as exc:
        # Fail CLOSED, unlike the freshness gate next door, and for the opposite
        # reason: there the unbounded thing was the silence, here it is the
        # walk. An unrationable repair that runs every hour would hold the
        # fleet-wide lock against every other workspace's cheap probe.
        logger.warning(
            "finreports: cannot ration the gap repair for %s — leaving it to the nightly pass: %s",
            chosen[0].name,
            exc,
        )
        return set()
    if not claimed:
        return set()
    bind_workspace(workspace_id)
    logger.info(
        "finreports: %s is short %d settlement day(s) — repairing now instead of "
        "waiting for its turn in the nightly rotation.",
        chosen[0].name,
        len(gaps[workspace_id]),
    )
    return {workspace_id}


__all__ = ["gap_repair_due"]
