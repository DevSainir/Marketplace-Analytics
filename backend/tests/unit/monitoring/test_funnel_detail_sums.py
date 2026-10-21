"""Unit tests for the per-day funnel DTOs of the SKU card.

The card's «Заказы, ₽» / «Выкупы, ₽» are DERIVED (count x seller price, in
roubles). Since 2026-09-29 the funnel row also stores WB's own sums — in the
workspace's settlement currency and NULL until the backfill reaches the day —
and those must never leak into the card: reading them broke every SKU card
with a 500 on the first deploy.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.monitoring.services.analytics.presenters import price_funnel_details
from tests.support.matrix_rows import DAY1, DAY2, _funnel_row, _price_row


def test_day_without_stored_money_is_priced_from_the_seller_price() -> None:
    """A row the backfill has not reached (sums NULL) still renders."""
    rows = [_funnel_row(DAY1, order_count=4, buyout_count=2)]

    details, order_total, buyout_total = price_funnel_details(rows, [_price_row(DAY1, seller=500)])

    assert (details[0].order_sum, details[0].buyout_sum) == (2000.0, 1000.0)
    assert (order_total, buyout_total) == (2000.0, 1000.0)


def test_unpriced_day_is_zero_even_when_wb_stored_its_own_sum() -> None:
    """WB's settlement-currency sum is not a rouble figure to fall back on."""
    row = _funnel_row(DAY2, order_count=3, buyout_count=1)
    row.order_sum = Decimal("41.70")
    row.buyout_sum = Decimal("13.90")

    details, order_total, buyout_total = price_funnel_details([row], [])

    assert (details[0].order_sum, details[0].buyout_sum) == (0.0, 0.0)
    assert (order_total, buyout_total) == (0.0, 0.0)
