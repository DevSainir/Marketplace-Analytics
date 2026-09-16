"""Harvest core for the ``finreports`` module.

Builds per-workspace WB clients from the decrypted token bundle, fetches the
dimensions, and persists them through :class:`IngestionService` in one atomic
transaction per workspace — mirroring the monitoring harvest's structure.

The finance walk is the exception to "fetch everything, then write it": it is
streamed into that transaction a page at a time, because a settlement window is
too large to hold. :func:`harvest_workspace` says what that costs and how the
all-or-nothing property survives it.

Split four ways by responsibility, this being the package's public face:
:mod:`sources` reads WB and writes nothing, :mod:`persistence` writes and reads
no WB, :mod:`workspace` composes the two into one workspace's harvest, and
:mod:`fleet` decides which workspaces a tick pays for. Nothing outside the
package imports a submodule — the two entrypoints below are the whole surface,
at the same paths they had before the split.
"""

from __future__ import annotations

from src.modules.finreports.tasks.harvest.fleet import harvest_all_workspaces
from src.modules.finreports.tasks.harvest.workspace import harvest_workspace

__all__ = [
    "harvest_all_workspaces",
    "harvest_workspace",
]
