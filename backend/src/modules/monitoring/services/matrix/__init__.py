"""Pure builder for the day x traffic-bucket metrics matrix.

Composes three persisted fact families into the workbook-shaped matrix served
by the SKU detail endpoint:

* ``AdvertisingStatDaily`` — full per-campaign daily totals (all zones).
* ``AdvertisingSearchStatDaily`` — the SEARCH-zone slice of the same days
  (from WB's search-cluster stats endpoint).
* ``SalesFunnelDaily`` — the organic funnel («Общая» / «Органика» columns).

Everything here is pure computation over already-fetched rows: no SQL, no I/O.
The package is split by pipeline stage, one responsibility per module:

* :mod:`~src.modules.monitoring.services.matrix.slices` — shared value objects
  (``_AdSlice``/``_BucketAcc``) and numeric helpers.
* :mod:`~src.modules.monitoring.services.matrix.assoc` — apportioning
  associated-variant conversions across a split campaign-day.
* :mod:`~src.modules.monitoring.services.matrix.classification` — campaign-day
  -> bucket classification, the search/shelves split, and significant-campaign
  selection.
* :mod:`~src.modules.monitoring.services.matrix.pricing` — per-day price/stock
  resolution and the derived ₽ values («Заказы/Выкупы, ₽», «СПП»).
* :mod:`~src.modules.monitoring.services.matrix.cells` — the per-cell metric
  formulas of every column family.
* :mod:`~src.modules.monitoring.services.matrix.base_state` — stage 1: raw fact
  rows -> the editable :class:`MatrixBaseState` working copy.
* :mod:`~src.modules.monitoring.services.matrix.build` — stage 2: working copy
  -> the display :class:`MetricsMatrixRead`.
* :mod:`~src.modules.monitoring.services.matrix.edit` — applying one user
  cell-edit to the working copy (formula inversion / display overrides).
* :mod:`~src.modules.monitoring.services.matrix.overrides` — mapping manual
  edits between the working copy and the persisted override rows.

This ``__init__`` is the package facade: every name consumers used from the
former flat ``matrix``/``matrix_edit``/``matrix_overrides`` modules is
re-exported here, so callers import from ``services.matrix`` unchanged.
"""

from src.modules.monitoring.services.matrix.base_state import (
    BUYOUT_LAG_END_DAYS,
    BUYOUT_LAG_START_DAYS,
    derive_base_state,
)
from src.modules.monitoring.services.matrix.build import (
    build_matrix_from_base,
    build_metrics_matrix,
)
from src.modules.monitoring.services.matrix.edit import apply_edit
from src.modules.monitoring.services.matrix.overrides import diff_to_overrides, overlay_overrides
from src.modules.monitoring.services.matrix.pricing import (
    ad_buyout_sum,
    ad_order_sum,
    price_for_day,
)

__all__ = [
    "BUYOUT_LAG_END_DAYS",
    "BUYOUT_LAG_START_DAYS",
    "ad_buyout_sum",
    "ad_order_sum",
    "apply_edit",
    "build_matrix_from_base",
    "build_metrics_matrix",
    "derive_base_state",
    "diff_to_overrides",
    "overlay_overrides",
    "price_for_day",
]
