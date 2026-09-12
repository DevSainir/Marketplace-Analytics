"""Public contract for the Workspaces module.

Other modules that need tenancy primitives (the validated workspace context
for routes, or decrypted token bundles for the harvest) import **only** from
here — never from ``services``/``repos``/``models``. This keeps the module's
internals free to change behind a stable surface, enforcing the "no horizontal
imports" architecture rule.
"""

from __future__ import annotations

from src.modules.workspaces.backfill import (
    BackfillLane,
    BackfillState,
    LaneStep,
    read_cursor,
    record_failure,
    record_progress,
    start_backfill,
)
from src.modules.workspaces.chain import claim_chain
from src.modules.workspaces.deps import WORKSPACE_HEADER, CurrentWorkspaceId
from src.modules.workspaces.schemas import WorkspaceTokenBundle
from src.modules.workspaces.services import (
    load_workspace_name,
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)

__all__ = [
    "WORKSPACE_HEADER",
    "BackfillLane",
    "BackfillState",
    "CurrentWorkspaceId",
    "LaneStep",
    "WorkspaceTokenBundle",
    "claim_chain",
    "load_workspace_name",
    "load_workspace_token_bundle",
    "load_workspace_token_bundles",
    "read_cursor",
    "record_failure",
    "record_progress",
    "start_backfill",
]
