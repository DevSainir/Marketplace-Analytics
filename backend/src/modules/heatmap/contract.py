"""Public contract for the ``heatmap`` module.

Nothing consumes it yet — the surface is HTTP-only — but a module without a
contract is one other code will eventually reach into sideways, and the
boundary test requires one. The read service and its response are what a future
consumer would want; the folding helpers stay internal.
"""

from src.modules.heatmap.schemas import HeatmapResponse
from src.modules.heatmap.services import HeatmapService

__all__ = ["HeatmapResponse", "HeatmapService"]
