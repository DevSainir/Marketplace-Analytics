"""The per-SKU, per-settlement-day cut other modules read — composition only.

Every figure comes out of the helpers the "By SKU" row is built with
(:func:`~.sku_report.sku_payout_net`), so a SKU's days add up to its window row:
the heatmap and the P&L cannot disagree about one article's money.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.schemas.sku_days import PnlSkuDay, PnlSkuDays
from src.modules.finreports.services.pnl.sku_report import sku_payout_net


def build_sku_days(
    aggregates: list[SettlementAggregate], *, costs: dict[int, Decimal], currency: str
) -> PnlSkuDays:
    """Turn the rollup's ``(day, nm_id)`` aggregates into the cut's cells.

    Args:
        aggregates: One per settled SKU-day, keyed ``(rr_dt, nm_id)``.
        costs: ``{nm_id: cost per unit}`` in ``currency``; an article absent
            from it is uncosted and its cells carry ``cogs=None``.
        currency: The window's settlement currency.
    """
    cells: list[PnlSkuDay] = []
    for aggregate in aggregates:
        # The rollup keys this cut by the pair; `key` is typed loosely because
        # every other cut keys by a single value.
        day, nm_id = cast(tuple[date, int], aggregate.key)
        cost = costs.get(int(nm_id))
        net_units = aggregate.sold_units - aggregate.returned_units
        cells.append(
            PnlSkuDay(
                nm_id=int(nm_id),
                day=day,
                revenue_seller=aggregate.sales_before_spp - aggregate.returns_before_spp,
                sold_units=aggregate.sold_units,
                returned_units=aggregate.returned_units,
                payout_net=sku_payout_net(aggregate),
                cogs=None if cost is None else cost * net_units,
            )
        )
    return PnlSkuDays(currency=currency, cells=cells)
