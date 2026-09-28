"""Business logic for the heatmap.

* :mod:`.metrics` — a cell's additive facts and the metrics read off them.
* :mod:`.periods` — the window cut into day / week / month columns.
* :mod:`.table` — folding SKU-day facts into rows and the «Итого» line.
* :mod:`.loader` — gathering the facts through other modules' contracts.
* :mod:`.heatmap` — the orchestrating read service.
* :mod:`.groups` — the seller-defined «Группы».
"""

from src.modules.heatmap.services.groups import SkuGroupService
from src.modules.heatmap.services.heatmap import HeatmapQuery, HeatmapService

__all__ = ["HeatmapQuery", "HeatmapService", "SkuGroupService"]
