"""Unit tests for the override overlay/diff mapping (services/matrix_overrides.py)."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import MatrixOverride
from src.modules.monitoring.schemas.matrix import (
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.matrix_overrides import (
    diff_to_overrides,
    overlay_overrides,
)

DAY = date(2026, 7, 1)


def _fact_base() -> MatrixBaseState:
    """A fact-derived base with one ad bucket and a funnel."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "manual_search": MatrixAdBucketBase(
                        views=40, clicks=4, add_to_cart=2, spend=20.0, orders=2, order_sum=500.0
                    )
                },
                unclassified=MatrixAdBucketBase(),
                funnel=MatrixFunnelBase(
                    open_count=200,
                    cart_count=20,
                    order_count=10,
                    seller_price=500.0,
                    customer_price=350.0,
                ),
            )
        ]
    )


def test_overlay_applies_stored_edits_with_type_coercion() -> None:
    """Overrides replace fact inputs; int fields coerce back to int."""
    base = _fact_base()

    overlay_overrides(
        base,
        [
            MatrixOverride(nm_id=1, stat_date=DAY, bucket="manual_search", field="views", value=99),
            MatrixOverride(
                nm_id=1, stat_date=DAY, bucket="funnel", field="seller_price", value=1234.5
            ),
        ],
    )

    bucket = base.days[0].buckets["manual_search"]
    assert bucket.views == 99
    assert isinstance(bucket.views, int)
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.seller_price == 1234.5


def test_overlay_skips_unknown_targets() -> None:
    """Overrides for an absent bucket/day are ignored (self-healing)."""
    base = _fact_base()

    overlay_overrides(
        base,
        [
            MatrixOverride(nm_id=1, stat_date=DAY, bucket="uni_shelves", field="views", value=5),
            MatrixOverride(
                nm_id=1, stat_date=date(2020, 1, 1), bucket="manual_search", field="views", value=5
            ),
        ],
    )

    assert "uni_shelves" not in base.days[0].buckets
    assert base.days[0].buckets["manual_search"].views == 40  # untouched


def test_diff_captures_only_changed_inputs() -> None:
    """A working copy diffs to exactly the input cells the user changed."""
    fact = _fact_base()
    working = _fact_base()
    working.days[0].buckets["manual_search"].spend = 33.0  # edited
    assert working.days[0].funnel is not None
    working.days[0].funnel.cart_count = 25  # edited

    rows = diff_to_overrides(nm_id=7, working=working, fact=fact)

    keyed = {(r["bucket"], r["field"]): r["value"] for r in rows}
    assert keyed == {("manual_search", "spend"): 33.0, ("funnel", "cart_count"): 25}
    assert all(r["nm_id"] == 7 and r["stat_date"] == DAY for r in rows)


def test_diff_ignores_unchanged_and_tainted() -> None:
    """No diff for an untouched copy; None order_sum is never diffed."""
    fact = _fact_base()
    fact.days[0].buckets["manual_search"].order_sum = None  # tainted split zone
    working = fact.model_copy(deep=True)

    assert diff_to_overrides(nm_id=7, working=working, fact=fact) == []


def test_overlay_then_diff_roundtrip() -> None:
    """Overlaying an override then diffing reproduces that same override."""
    fact = _fact_base()
    working = fact.model_copy(deep=True)

    overlay_overrides(
        working,
        [MatrixOverride(nm_id=1, stat_date=DAY, bucket="manual_search", field="orders", value=9)],
    )

    rows = diff_to_overrides(nm_id=1, working=working, fact=fact)

    assert rows == [
        {"nm_id": 1, "stat_date": DAY, "bucket": "manual_search", "field": "orders", "value": 9}
    ]


def test_display_override_overlay_and_diff_roundtrip() -> None:
    """A ``cell`` (display) override overlays onto cell_overrides and diffs back."""
    fact = _fact_base()
    working = fact.model_copy(deep=True)

    overlay_overrides(
        working,
        [
            MatrixOverride(
                nm_id=1, stat_date=DAY, bucket="cell", field="total:order_sum", value=42000
            ),
            MatrixOverride(
                nm_id=1, stat_date=DAY, bucket="cell", field="uni_catalog:views", value=7
            ),
        ],
    )

    assert working.days[0].cell_overrides == {"total:order_sum": 42000.0, "uni_catalog:views": 7.0}

    # The fact base has no cell overrides, so every entry diffs back out.
    rows = diff_to_overrides(nm_id=1, working=working, fact=fact)
    keyed = {(r["bucket"], r["field"]): r["value"] for r in rows}
    assert keyed == {("cell", "total:order_sum"): 42000.0, ("cell", "uni_catalog:views"): 7.0}


def test_buyout_percent_roundtrips_as_a_day_level_input() -> None:
    """«Процент выкупа» persists as a ``day`` row and comes back as a fact.

    It is harvested, so a manager's correction has to survive a save the same
    way an edited count does — otherwise everything derived from it («Выкупы,
    ₽», both ДРР rows) reverts on the next read.
    """
    fact = _fact_base()  # no cohort served for this day
    working = fact.model_copy(deep=True)
    working.days[0].lagged_buyout_percent = 34.5

    rows = diff_to_overrides(nm_id=1, working=working, fact=fact)

    assert rows == [
        {
            "nm_id": 1,
            "stat_date": DAY,
            "bucket": "day",
            "field": "lagged_buyout_percent",
            "value": 34.5,
        }
    ]

    # ...and overlays back onto a fresh fact base.
    restored = _fact_base()
    overlay_overrides(
        restored,
        [
            MatrixOverride(
                nm_id=1, stat_date=DAY, bucket="day", field="lagged_buyout_percent", value=34.5
            )
        ],
    )
    assert restored.days[0].lagged_buyout_percent == 34.5


def test_restoring_an_orders_override_repairs_the_viewed_breakdown_row() -> None:
    """A reloaded own-count lands on the viewed SKU's row of the hover too.

    Only the totals are stored as numbers; the per-variant rows are re-derived
    from facts. Without this the reloaded breakdown would still list the
    harvested 2 while the cell claims 6, and the rows would stop summing.
    """
    base = _fact_base()
    bucket = base.days[0].buckets["manual_search"]
    bucket.assoc_orders = 5
    bucket.assoc_skus = [
        AssocSkuCount(nm_id=111, orders=2),
        AssocSkuCount(nm_id=222, orders=3),
    ]

    overlay_overrides(
        base,
        [
            MatrixOverride(
                nm_id=111, stat_date=DAY, bucket="manual_search", field="orders", value=6
            ),
            MatrixOverride(
                nm_id=111, stat_date=DAY, bucket="manual_search", field="assoc_orders", value=9
            ),
        ],
        nm_id=111,
    )

    rows = {sku.nm_id: sku.orders for sku in bucket.assoc_skus}
    assert rows == {111: 6, 222: 3}
    assert sum(rows.values()) == bucket.assoc_orders == 9
