"""Unit tests for the matrix reverse-solver (services/matrix_edit.py).

Covers the editability contract: direct input sets, numerator reverse-solves
(incl. the user's order_conversion→orders example), the traffic-share
cross-bucket redistribution, the funnel-backed «Общая»/«Органика» solves, and
a verbatim display override for every non-invertible cell (all cells editable).
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.exceptions import ValidationError
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixCellEdit,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.matrix import build_matrix_from_base
from src.modules.monitoring.services.matrix_edit import apply_edit

DAY = date(2026, 7, 1)


def _base() -> MatrixBaseState:
    """A one-day working copy: two ad buckets, an unclassified remainder, funnel."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "uni_search": MatrixAdBucketBase(
                        views=30, clicks=3, add_to_cart=1, spend=15.0, orders=1, order_sum=None
                    ),
                    "manual_search": MatrixAdBucketBase(
                        views=40, clicks=4, add_to_cart=10, spend=20.0, orders=2, order_sum=500.0
                    ),
                },
                unclassified=MatrixAdBucketBase(views=10, clicks=1, spend=5.0),
                funnel=MatrixFunnelBase(
                    open_count=200,
                    cart_count=20,
                    order_count=10,
                    seller_price=500.0,
                    customer_price=350.0,
                ),
                lagged_buyout_percent=50.0,
            )
        ]
    )


def _edit(bucket: str, metric: str, value: float) -> MatrixBaseState:
    """Apply one edit to the reference base and return the new base."""
    return apply_edit(_base(), MatrixCellEdit(day=DAY, bucket=bucket, metric=metric, value=value))


def _cell(base: MatrixBaseState, key: str, bucket: str) -> float | None:
    """Read a derived cell (day 0) from the matrix built from ``base``."""
    matrix = build_matrix_from_base(base)
    row = next(r for r in matrix.rows if r.key == key)
    return row.values[MATRIX_BUCKETS.index(bucket)]


def _bucket(base: MatrixBaseState, name: str) -> MatrixAdBucketBase:
    """Return the working-copy bucket input on day 0."""
    return base.days[0].buckets[name]


# --------------------------------------------------------------------------- #
# Direct input edits
# --------------------------------------------------------------------------- #
def test_direct_input_set_and_dependents_recompute() -> None:
    """Editing «Показы» sets views and recomputes CTR/CPM/traffic share."""
    base = _edit("manual_search", "views", 80)
    assert _bucket(base, "manual_search").views == 80
    # CTR = 4/80*100 = 5%, CPM = 20/80*1000 = 250.
    assert _cell(base, "ctr", "manual_search") == 5.0
    assert _cell(base, "cpm", "manual_search") == 250.0


def test_counts_are_non_negative_integers() -> None:
    """A negative or fractional count edit clamps to a non-negative integer."""
    assert _bucket(_edit("uni_search", "clicks", -5), "uni_search").clicks == 0
    assert _bucket(_edit("uni_search", "clicks", 2.6), "uni_search").clicks == 3


# --------------------------------------------------------------------------- #
# Reverse-solve: numerator convention
# --------------------------------------------------------------------------- #
def test_order_conversion_back_solves_orders() -> None:
    """The user's example: editing «Конверсия в заказ» changes «Заказы»."""
    # order_conversion = orders/add_to_cart*100; add_to_cart=10 held → orders=5.
    base = _edit("manual_search", "order_conversion", 50)
    assert _bucket(base, "manual_search").orders == 5
    assert _cell(base, "orders", "manual_search") == 5
    assert _cell(base, "order_conversion", "manual_search") == 50.0
    # cost_per_order = spend/orders = 20/5 = 4 recomputed downstream.
    assert _cell(base, "cost_per_order", "manual_search") == 4.0


def test_ctr_back_solves_clicks_holding_views() -> None:
    """CTR = clicks/views*100 → solve clicks, hold views."""
    base = _edit("manual_search", "ctr", 25)  # 25% of 40 views = 10 clicks
    assert _bucket(base, "manual_search").clicks == 10
    assert _cell(base, "ctr", "manual_search") == 25.0


def test_cpc_back_solves_spend_holding_clicks() -> None:
    """CPC = spend/clicks → solve spend, hold clicks."""
    base = _edit("manual_search", "cpc", 7)  # 7 * 4 clicks = 28 spend
    assert _bucket(base, "manual_search").spend == 28.0
    assert _cell(base, "cpc", "manual_search") == 7.0


def test_drr_orders_back_solves_spend() -> None:
    """ДРР от заказов = spend/order_sum*100 → solve spend (needs ad revenue)."""
    base = _edit("manual_search", "drr_orders", 10)  # 10% of 500 = 50 spend
    assert _bucket(base, "manual_search").spend == 50.0


# --------------------------------------------------------------------------- #
# Traffic share (redistributes WITHIN a bid type)
# --------------------------------------------------------------------------- #
def _dual_zone_base() -> MatrixBaseState:
    """A unified campaign shown in both zones (uni_search + uni_shelves)."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "uni_search": MatrixAdBucketBase(views=30, clicks=3, spend=15.0),
                    "uni_shelves": MatrixAdBucketBase(views=70, clicks=7, spend=35.0),
                },
                funnel=MatrixFunnelBase(open_count=200, cart_count=20, order_count=10),
            )
        ]
    )


def test_traffic_share_redistributes_within_bid_type() -> None:
    """Setting a unified zone's «Доля трафика» solves it against the other zone."""
    # The two unified zones normalize together (uni_shelves = 70 held fixed).
    # Target 50% → uni_search views = 70.
    base = apply_edit(
        _dual_zone_base(),
        MatrixCellEdit(day=DAY, bucket="uni_search", metric="traffic_share", value=50),
    )
    assert base.days[0].buckets["uni_search"].views == 70
    matrix = build_matrix_from_base(base)
    share = next(r for r in matrix.rows if r.key == "traffic_share")
    assert share.values[MATRIX_BUCKETS.index("uni_search")] == 50.0
    assert share.values[MATRIX_BUCKETS.index("uni_shelves")] == 50.0


def test_traffic_share_unreachable_target_becomes_override() -> None:
    """An unreachable «Доля трафика» target can't redistribute, so it is shown
    verbatim as a display override (0/100%, or a single-bucket type)."""
    base = apply_edit(
        _dual_zone_base(),
        MatrixCellEdit(day=DAY, bucket="uni_search", metric="traffic_share", value=100),
    )
    assert _cell(base, "traffic_share", "uni_search") == 100.0
    # uni_search is the ONLY unified bucket in _base() -> always 100%, no solve.
    assert _cell(_edit("uni_search", "traffic_share", 42), "traffic_share", "uni_search") == 42.0


# --------------------------------------------------------------------------- #
# «Общая» and «Органика»
# --------------------------------------------------------------------------- #
def test_total_cart_conversion_solves_funnel_cart_count() -> None:
    """«Общая» конверсия в корзину = cart/open*100 → solve cart_count."""
    base = _edit("total", "cart_conversion", 15)  # 15% of 200 opens = 30 carts
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.cart_count == 30
    assert _cell(base, "carts", "total") == 30


def test_total_seller_price_edit_recomputes_volumes_and_spp() -> None:
    """Editing «Цена продавца» recomputes «Заказы, ₽», «Выкупы, ₽», «СПП»."""
    base = _edit("total", "seller_price", 1000)
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.seller_price == 1000.0
    # order_count 10 x 1000 = 10000.
    assert _cell(base, "order_sum", "total") == 10000.0
    # «Выкупы, ₽» is order-date: «Заказы, ₽» 10000 x «Процент выкупа» 50% = 5000.
    assert _cell(base, "buyout_sum", "total") == 5000.0
    # СПП = (1000 - 350) / 1000 x 100.
    assert _cell(base, "spp", "total") == 65.0


def test_total_customer_price_edit_recomputes_spp() -> None:
    """Editing «Цена покупателя» recomputes «СПП» (seller held)."""
    base = _edit("total", "customer_price", 250)
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.customer_price == 250.0
    assert _cell(base, "spp", "total") == 50.0  # (500 - 250) / 500 x 100


def test_organic_clicks_solves_open_count_holding_ads() -> None:
    """«Органика» клики = open - ad_clicks → solve open_count (hold ads)."""
    # ad clicks = 3 + 4 + 1 (unclassified) = 8. organic set to 300 → open = 308.
    base = _edit("organic", "clicks", 300)
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.open_count == 308
    assert _cell(base, "clicks", "organic") == 300
    assert _cell(base, "clicks", "total") == 308


# --------------------------------------------------------------------------- #
# Non-invertible cells → display overrides (EVERY cell is editable)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("bucket", "metric"),
    [
        ("manual_search", "drr_sales"),  # no ad buyout data
        ("manual_search", "buyout_percent"),  # funnel-only
        ("uni_search", "order_sum"),  # tainted split zone (None)
        ("uni_catalog", "views"),  # legacy empty zone
        ("total", "spend"),  # cross-bucket roll-up
        ("total", "drr_orders"),  # cross-bucket roll-up
        ("total", "buyout_percent"),  # lagged window
        ("total", "order_sum"),  # derived from price
        ("total", "buyout_sum"),  # sale-date fact
        ("total", "spp"),  # derived from prices
        ("organic", "spend"),  # difference has no such input
    ],
)
def test_noninvertible_cell_becomes_display_override(bucket: str, metric: str) -> None:
    """A non-invertible cell is still editable — stored + shown verbatim."""
    base = _edit(bucket, metric, 123)
    assert base.days[0].cell_overrides[f"{bucket}:{metric}"] == 123.0
    assert _cell(base, metric, bucket) == 123.0


def test_absent_bucket_edit_becomes_display_override() -> None:
    """A bucket that delivered nothing that day («—») is editable via override."""
    base = _edit("uni_shelves", "views", 5)  # uni_shelves absent from the base
    assert _cell(base, "views", "uni_shelves") == 5.0


def test_invertible_edit_supersedes_stale_override() -> None:
    """A successful dynamic edit drops any stale display override on the cell."""
    seed = _base()
    seed.days[0].cell_overrides["total:orders"] = 999.0
    base = apply_edit(seed, MatrixCellEdit(day=DAY, bucket="total", metric="orders", value=7))
    assert "total:orders" not in base.days[0].cell_overrides
    assert _cell(base, "orders", "total") == 7  # the back-solved funnel value shows


def test_edit_on_unknown_day_rejected() -> None:
    """An edit targeting a day outside the window is rejected."""
    with pytest.raises(ValidationError):
        apply_edit(
            _base(),
            MatrixCellEdit(day=date(2020, 1, 1), bucket="manual_search", metric="views", value=1),
        )
