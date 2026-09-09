"""Account-wide chart series DTOs (the «Сравнение SKU» page).

The per-SKU page answers «how is this card doing». This one answers «how is the
account doing», over the same days and the same metric names, for any subset of
SKUs the user picks.

The payload deliberately reuses :class:`MetricsMatrixRead`: the frontend already
knows how to map that shape onto a chart, and using it here means the two pages
cannot drift into two different notions of what «Заказы» means. Only two buckets
are populated — ``total`` and ``organic``. The traffic-type columns are absent
on purpose (see :meth:`AdvertisingRepository.daily_totals`): a bucket is the
result of classifying a campaign-day for ONE card, and that judgement does not
survive being summed across an account.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.modules.monitoring.schemas.matrix import MetricsMatrixRead
from src.modules.monitoring.schemas.summary import MetricWindow


class AggregateChartsResponse(BaseModel):
    """Day-by-day metrics for a set of SKUs, summed."""

    window: MetricWindow
    nm_ids: list[int] = Field(
        default_factory=list,
        description=(
            "The SKUs actually included. Empty request means every SKU in the "
            "workspace, and this field reports which those turned out to be — "
            "so a chart drawn from a stale picker cannot silently claim to "
            "cover cards it never saw."
        ),
    )
    sku_count: int = Field(description="How many SKUs contributed at least one day.")
    matrix: MetricsMatrixRead = Field(
        description=(
            "Day x bucket matrix carrying only «Общая» and «Органика». Every "
            "value is computed server-side, exactly like the per-SKU matrix — "
            "ratios from the summed totals, never an average of per-SKU ratios."
        )
    )
