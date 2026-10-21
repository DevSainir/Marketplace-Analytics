"""Harvest core for the ``finreports`` module.

Builds per-workspace WB clients from the decrypted token bundle, walks the
finance (settlement) report and persists it through :class:`IngestionService`
— mirroring the monitoring harvest's structure.

The walk is streamed into the database a page at a time rather than fetched
whole and written once, because a settlement window is too large to hold.
:func:`harvest_workspace` says what that costs.

Split by responsibility, this being the package's public face:
:mod:`persistence` moves the watermark, :mod:`ledger` reads and books the report
headers, :mod:`workspace` composes one workspace's harvest, and :mod:`fleet`
decides which workspaces a tick pays for. Nothing outside the
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
