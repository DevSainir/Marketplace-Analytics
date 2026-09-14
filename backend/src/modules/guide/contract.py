"""Public contract for the Guide module.

Nothing in the app reads this data yet — that is the module's whole premise —
so the surface is deliberately narrow: the catalogue (so another module can ask
what is being kept and why), the cadence enum, and the entry point the Celery
tasks drive.

When a captured feed graduates into a module that uses it, the typed table
belongs there and the capture stays here: this one keeps the history the new
table cannot reach back for.
"""

from __future__ import annotations

from src.modules.guide.services import capture_cadence
from src.modules.guide.sources import GUIDE_SOURCES, GuideCadence, GuideSource, sources_for

__all__ = [
    "GUIDE_SOURCES",
    "GuideCadence",
    "GuideSource",
    "capture_cadence",
    "sources_for",
]
