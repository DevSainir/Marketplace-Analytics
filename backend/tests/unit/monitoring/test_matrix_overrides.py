"""Unit tests for the override overlay/diff mapping (services/matrix/overrides.py)."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import MatrixOverride
from src.modules.monitoring.schemas.matrix import (
    AssocSkuCount,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.matrix import (
    diff_to_overrides,
    overlay_overrides,
)
from tests.support.matrix_rows import _ad_bucket

DAY = date(2026, 7, 1)


def _fact_base() -> MatrixBaseState:
    """A fact-derived base with one ad bucket and a funnel."""
    return MatrixBaseState(
        days=[
            MatrixDayBase(
                day=DAY,
                has_advertising=True,
                buckets={
                    "manual_search": _ad_bucket(
                        views=40, clicks=4, add_to_cart=2, spend=20.0, orders=2, order_sum=500.0
                    )
                },
                unclassified=_ad_bucket(),
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
                nm_id=1, stat_date=DAY, bucket="cell", field="cpc_shelves:views", value=7
            ),
        ],
    )

    assert working.days[0].cell_overrides == {"total:order_sum": 42000.0, "cpc_shelves:views": 7.0}

    # The fact base has no cell overrides, so every entry diffs back out.
    rows = diff_to_overrides(nm_id=1, working=working, fact=fact)
    keyed = {(r["bucket"], r["field"]): r["value"] for r in rows}
    assert keyed == {("cell", "total:order_sum"): 42000.0, ("cell", "cpc_shelves:views"): 7.0}


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
    """A reloaded card share lands on the viewed SKU's row of the hover too.

    Only the numbers are stored; the per-variant rows are re-derived from facts.
    Without this the reloaded breakdown would still list the harvested 2 while
    the cell claims 9, and the rows would stop summing.
    """
    base = _fact_base()
    bucket = base.days[0].buckets["manual_search"]
    bucket.orders = 5
    bucket.sku.orders = 2
    bucket.assoc_skus = [
        AssocSkuCount(nm_id=111, orders=2),
        AssocSkuCount(nm_id=222, orders=3),
    ]

    overlay_overrides(
        base,
        [
            MatrixOverride(
                nm_id=111, stat_date=DAY, bucket="manual_search", field="orders", value=9
            ),
            MatrixOverride(
                nm_id=111, stat_date=DAY, bucket="manual_search", field="sku.orders", value=6
            ),
        ],
        nm_id=111,
    )

    rows = {sku.nm_id: sku.orders for sku in bucket.assoc_skus}
    assert rows == {111: 6, 222: 3}
    assert sum(rows.values()) == bucket.orders == 9


def test_an_edited_card_share_is_persisted_beside_the_campaigns_number() -> None:
    """An ad edit moves both sides, so both are diffed into overrides.

    «Общая» and «Органика» are built from the card's share: persisting only the
    campaign's number would reload a corrected column with the harvested share
    underneath it.
    """
    fact = _fact_base()
    working = _fact_base()
    bucket = working.days[0].buckets["manual_search"]
    bucket.orders = 6
    bucket.sku.orders = 4

    rows = diff_to_overrides(nm_id=111, working=working, fact=fact)

    assert {(row["field"], row["value"]) for row in rows} == {("orders", 6), ("sku.orders", 4)}
