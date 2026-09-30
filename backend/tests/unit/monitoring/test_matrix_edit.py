"""Unit tests for the matrix reverse-solver (services/matrix/edit.py).

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
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixCellEdit,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.matrix import apply_edit, build_matrix_from_base
from tests.support.matrix_rows import _ad_bucket

DAY = date(2026, 7, 1)


def _base() -> MatrixBaseState:
    """A one-day working copy: two ad buckets, an unclassified remainder, funnel."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "uni_search": _ad_bucket(
                        views=30, clicks=3, add_to_cart=1, spend=15.0, orders=1, order_sum=None
                    ),
                    "manual_search": _ad_bucket(
                        views=40, clicks=4, add_to_cart=10, spend=20.0, orders=2, order_sum=500.0
                    ),
                },
                unclassified=_ad_bucket(views=10, clicks=1, spend=5.0),
                funnel=MatrixFunnelBase(
                    open_count=200,
                    cart_count=20,
                    order_count=10,
                    seller_price=500.0,
                    customer_price=350.0,
                    price_currency="RUB",
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
    """ДРР от заказов = spend/(orders x price)*100 → solve spend.

    The denominator is the zone's DERIVED revenue — 2 orders x 500 ₽ — so 10%
    of 1 000 ₽ is 100 ₽ of spend.
    """
    base = _edit("manual_search", "drr_orders", 10)

    assert _bucket(base, "manual_search").spend == 100.0


def test_ad_order_sum_back_solves_the_orders_count() -> None:
    """«Заказы, ₽» in an ad zone is orders x price → solve the orders count.

    Writing the stored ``order_sum`` would be invisible (the cell is derived),
    so the edit moves the number the display actually reads.
    """
    base = _edit("manual_search", "order_sum", 2500)  # 2500 / 500 ₽

    assert _bucket(base, "manual_search").orders == 5
    assert "manual_search:order_sum" not in base.days[0].cell_overrides


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
                    "uni_search": _ad_bucket(views=30, clicks=3, spend=15.0),
                    "uni_shelves": _ad_bucket(views=70, clicks=7, spend=35.0),
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
        ("manual_search", "drr_sales"),  # one merged cell over a campaign
        ("manual_search", "buyout_percent"),  # funnel-only
        ("uni_catalog", "views"),  # legacy empty zone
        ("total", "spend"),  # cross-bucket roll-up
        ("total", "drr_orders"),  # cross-bucket roll-up
        ("total", "buyout_sum"),  # derived from count x price x buyout%
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


# --------------------------------------------------------------------------- #
# «Процент выкупа» and «Заказы, ₽» are inputs, not display paint
# --------------------------------------------------------------------------- #
def test_buyout_percent_is_an_input_that_moves_the_buyout_value() -> None:
    """It is harvested, not computed — so editing it recomputes what it feeds.

    The base has 10 orders x 500 ₽ at 50% -> 2 500 ₽ of buyouts. Doubling the
    percent doubles that, in «Общая» AND in the ad zones, instead of painting a
    number over the one cell.
    """
    base = _edit("total", "buyout_percent", 100)

    assert base.days[0].lagged_buyout_percent == 100.0
    assert "total:buyout_percent" not in base.days[0].cell_overrides
    assert _cell(base, "buyout_sum", "total") == 5000.0  # 10 x 500 x 100%
    # The ad zone follows too: its own 2 orders x 500 ₽ x 100%.
    assert _cell(base, "buyout_sum", "manual_search") == 1000.0


def test_total_order_sum_solves_the_count_and_leaves_ads_alone() -> None:
    """«Заказы, ₽» in «Общая» solves the funnel count — not the price, not ads."""
    base = _edit("total", "order_sum", 10000)  # 10 000 / 500 ₽
    day = base.days[0]

    assert day.funnel is not None
    assert day.funnel.order_count == 20
    assert day.funnel.seller_price == 500.0  # the price is never rewritten
    # The advertising zones keep their own orders; only the SKU-wide count moved.
    assert day.buckets["manual_search"].orders == _base().days[0].buckets["manual_search"].orders
    assert _cell(base, "order_sum", "total") == 10000.0
    assert _cell(base, "buyout_sum", "total") == 5000.0  # follows the count


# --------------------------------------------------------------------------- #
# Associative breakdown stays consistent when a zone's own count is edited
# --------------------------------------------------------------------------- #
VIEWED_NM_ID = 111
OTHER_NM_ID = 222


def _assoc_base() -> MatrixBaseState:
    """One ad zone whose campaign booked orders on a second variant too."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "manual_search": _ad_bucket(
                        views=40,
                        clicks=4,
                        add_to_cart=10,
                        spend=20.0,
                        # The campaign booked 5 orders, 2 of them on this card.
                        orders=5,
                        sku_orders=2,
                        assoc_skus=[
                            AssocSkuCount(nm_id=VIEWED_NM_ID, add_to_cart=10, orders=2),
                            AssocSkuCount(nm_id=OTHER_NM_ID, add_to_cart=0, orders=3),
                        ],
                    )
                },
                funnel=MatrixFunnelBase(open_count=200, cart_count=20, order_count=10),
            )
        ]
    )


def test_editing_a_zones_orders_sets_the_campaigns_total() -> None:
    """The cell IS the campaign's all-variant count, so that is what an edit sets.

    The zone took 2 of the campaign's 5 orders, the other variant 3. Typing 6
    into the cell means the campaign delivered 6: the other variant's 3 are
    harvested facts and stay, so the viewed card's own slice absorbs the whole
    move (to 3) and the hover's rows still add up to the number in the cell.
    """
    base = apply_edit(
        _assoc_base(),
        MatrixCellEdit(day=DAY, bucket="manual_search", metric="orders", value=6),
        viewed_nm_id=VIEWED_NM_ID,
    )
    bucket = _bucket(base, "manual_search")

    assert bucket.orders == 6  # the cell now reads 6
    assert bucket.sku.orders == 3  # 6 - the other variant's untouched 3
    rows = {sku.nm_id: sku.orders for sku in bucket.assoc_skus}
    assert rows[VIEWED_NM_ID] == 3  # the viewed row follows its own slice
    assert rows[OTHER_NM_ID] == 3  # the other variant is untouched
    assert sum(rows.values()) == bucket.orders  # the hover adds up


def test_a_zone_without_associated_variants_moves_both_counts_together() -> None:
    """With no associated share, the campaign's count and the card's own are one.

    Every cart of this zone was booked on the viewed card (10 of 10), so there
    is no other variant to hold fixed and the edit lands on both numbers.
    """
    base = apply_edit(
        _assoc_base(),
        MatrixCellEdit(day=DAY, bucket="manual_search", metric="carts", value=25),
        viewed_nm_id=VIEWED_NM_ID,
    )
    bucket = _bucket(base, "manual_search")

    assert bucket.add_to_cart == 25
    assert bucket.sku.add_to_cart == 25


def test_a_total_below_the_associated_share_shrinks_the_breakdown() -> None:
    """Typing under the associated remainder scales the other variants down.

    The other variant holds 3 of the campaign's 5 orders. Correcting the cell
    to 2 leaves no room for them: the viewed card's own slice floors at zero
    and the associated rows are rescaled, so the hover never lists more than
    the cell above it.
    """
    base = apply_edit(
        _assoc_base(),
        MatrixCellEdit(day=DAY, bucket="manual_search", metric="orders", value=2),
        viewed_nm_id=VIEWED_NM_ID,
    )
    bucket = _bucket(base, "manual_search")

    assert bucket.orders == 2
    assert bucket.sku.orders == 0
    rows = {sku.nm_id: sku.orders for sku in bucket.assoc_skus}
    assert rows[OTHER_NM_ID] == 2
    assert sum(rows.values()) == bucket.orders


# --------------------------------------------------------------------------- #
# ДРР divides the numbers shown above it
# --------------------------------------------------------------------------- #
def test_total_spend_override_moves_only_the_drr_rows() -> None:
    """«Затраты, ₽» in «Общая» is a roll-up: correcting it retargets both ДРР.

    It has no unique back-distribution across the zones, so it stays a display
    override — but the ratios that divide by it must quote the corrected
    number. Nothing else moves: not CPC, not the campaign's own ДРР.
    """
    base = _edit("total", "spend", 100)

    # 100 / 5 000 ₽ of orders, and 100 / 2 500 ₽ of buyouts.
    assert _cell(base, "drr_orders", "total") == 2.0
    assert _cell(base, "drr_sales", "total") == 4.0
    # CPC still reads the real harvested spend (40 ₽ over 8 clicks).
    assert _cell(base, "cpc", "total") == 5.0
    # The campaign column judges itself on its own spend, untouched.
    assert _cell(base, "drr_sales", "manual_search") == _cell(_base(), "drr_sales", "manual_search")


def test_total_buyout_override_moves_only_drr_sales() -> None:
    """A corrected «Выкупы, ₽» retargets ДРР от продаж and nothing else."""
    base = _edit("total", "buyout_sum", 1000)

    assert _cell(base, "buyout_sum", "total") == 1000.0
    assert _cell(base, "drr_sales", "total") == 4.0  # 40 ₽ / 1 000 ₽
    # «ДРР от заказов» divides by order revenue, so it stays put...
    assert _cell(base, "drr_orders", "total") == _cell(_base(), "drr_orders", "total")
    # ...and the buyout percent it was derived from is not rewritten backwards.
    assert base.days[0].lagged_buyout_percent == 50.0


def test_a_zones_buyout_override_moves_its_campaign_drr() -> None:
    """The same rule in an ad column: the campaign's ДРР follows its own cells."""
    base = _edit("manual_search", "buyout_sum", 200)

    assert _cell(base, "buyout_sum", "manual_search") == 200.0
    assert _cell(base, "drr_sales", "manual_search") == 10.0  # 20 ₽ / 200 ₽
