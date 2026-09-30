"""The matrix never adds or divides money of two currencies.

On «Демо» the prices are in RUB, WB's funnel order sums in KGS, and each
campaign bills in what it was created in — RUB before 20.08.2026, KGS after.
The order money is WB's own KGS funnel sum, so a KGS campaign's ДРР divides
сомы by сомы with no rate of ours; a RUB campaign's ДРР, and a spend total over
campaigns of both currencies, are «—» until the service converts
(``CONVERSION-TODO``).
"""

from __future__ import annotations

from src.modules.monitoring.schemas.matrix import MatrixCellEdit
from src.modules.monitoring.services.matrix import (
    apply_edit,
    build_metrics_matrix,
    derive_base_state,
)
from tests.support.matrix_rows import (
    DAY1,
    _ad_row,
    _campaign,
    _cell,
    _funnel_row,
    _matrix,
    _price_row,
)

#: 10 orders at 4 000 ₽ that WB valued at 41 480 с — the rate of 1.037.
_FUNNEL_KGS = _funnel_row(
    DAY1, open_count=500, cart_count=40, order_count=10, order_sum=41480.0, currency="KGS"
)
_PRICE = _price_row(DAY1, seller=4000, customer=3000)
_MANUAL_SEARCH = {1: _campaign(1, "manual", search=True, shelves=False)}


def _one_campaign(currency: str, funnel=_FUNNEL_KGS) -> dict[str, list[float | None]]:
    """One manual search campaign spending 1 037 in ``currency`` for 2 orders."""
    return _matrix(
        campaigns=_MANUAL_SEARCH,
        ad_rows=[_ad_row(1, DAY1, views=1000, clicks=50, spend=1037, orders=2, currency=currency)],
        funnel_rows=[funnel],
        price_snapshots=[_PRICE],
    )


def test_the_order_money_is_wbs_own_funnel_sum() -> None:
    rows = _one_campaign("KGS")

    assert _cell(rows, "order_sum", 0, "total") == 41480.0
    # The campaign's 2 orders at WB's value of one order that day.
    assert _cell(rows, "order_sum", 0, "manual_search") == 8296.0


def test_a_kgs_campaigns_drr_divides_soms_by_soms() -> None:
    rows = _one_campaign("KGS")

    assert _cell(rows, "drr_orders", 0, "manual_search") == 12.5  # 1037 / 8296
    assert _cell(rows, "drr_orders", 0, "total") == 2.5  # 1037 / 41480


def test_a_rub_campaigns_drr_is_blank_against_kgs_orders() -> None:
    rows = _one_campaign("RUB")

    assert _cell(rows, "drr_orders", 0, "manual_search") is None
    assert _cell(rows, "drr_orders", 0, "total") is None
    assert _cell(rows, "drr_sales", 0, "total") is None
    # The spend itself is one currency and still shown.
    assert _cell(rows, "spend", 0, "manual_search") == 1037.0
    assert _cell(rows, "cpc", 0, "total") == 20.74


def test_a_day_wb_served_no_sum_falls_back_to_the_price() -> None:
    """Orders at the seller price, in the prices' currency — so a RUB campaign pairs."""
    no_sum = _funnel_row(DAY1, open_count=500, cart_count=40, order_count=10)
    rows = _one_campaign("RUB", funnel=no_sum)

    assert _cell(rows, "order_sum", 0, "total") == 40000.0
    assert _cell(rows, "drr_orders", 0, "manual_search") == 12.96  # 1037 / 8000


def test_a_spend_total_over_two_currencies_is_blank() -> None:
    campaigns = {
        1: _campaign(1, "manual", search=True, shelves=False),
        2: _campaign(2, "manual", search=False, shelves=True),
    }
    rows = _matrix(
        campaigns=campaigns,
        ad_rows=[
            _ad_row(1, DAY1, views=1000, clicks=50, spend=1000, orders=1, currency="RUB"),
            _ad_row(2, DAY1, views=900, clicks=30, spend=900, orders=1, currency="KGS"),
        ],
        funnel_rows=[_FUNNEL_KGS],
        price_snapshots=[_PRICE],
    )

    assert _cell(rows, "spend", 0, "manual_search") == 1000.0
    assert _cell(rows, "spend", 0, "manual_shelves") == 900.0
    for metric in ("spend", "cpc", "cpm", "cost_per_order", "drr_orders"):
        assert _cell(rows, metric, 0, "total") is None, metric
    # Each zone is one currency: the KGS one pairs with the KGS orders.
    assert _cell(rows, "drr_orders", 0, "manual_shelves") is not None
    assert _cell(rows, "drr_orders", 0, "manual_search") is None


def test_the_matrix_states_each_days_currencies() -> None:
    matrix = build_metrics_matrix(
        date_from=DAY1,
        date_to=DAY1,
        funnel_rows=[_FUNNEL_KGS],
        ad_rows=[_ad_row(1, DAY1, views=1000, clicks=50, spend=1037, orders=2, currency="KGS")],
        search_rows=[],
        campaigns=_MANUAL_SEARCH,
        price_snapshots=[_PRICE],
        price_currency="RUB",
    )

    [day] = matrix.currencies
    assert day.orders == "KGS"
    assert day.ads == {"manual_search": ["KGS"], "total": ["KGS"]}


def test_editing_the_order_money_solves_the_count_at_wbs_value() -> None:
    base = derive_base_state(
        date_from=DAY1,
        date_to=DAY1,
        funnel_rows=[_FUNNEL_KGS],
        ad_rows=[],
        search_rows=[],
        campaigns={},
        price_snapshots=[_PRICE],
        price_currency="RUB",
    )
    edited = apply_edit(
        base, MatrixCellEdit(day=DAY1, bucket="total", metric="order_sum", value=20740.0)
    )

    assert edited.days[0].funnel is not None
    assert edited.days[0].funnel.order_count == 5
