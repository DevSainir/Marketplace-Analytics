"""Unit tests for the override overlay/diff mapping (services/matrix_overrides.py)."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import MatrixOverride
from src.modules.monitoring.schemas.matrix import (
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
                    order_sum=5000.0,
                    buyout_sum=2500.0,
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
                nm_id=1, stat_date=DAY, bucket="funnel", field="order_sum", value=1234.5
            ),
        ],
    )
    bucket = base.days[0].buckets["manual_search"]
    assert bucket.views == 99 and isinstance(bucket.views, int)
    assert base.days[0].funnel is not None
    assert base.days[0].funnel.order_sum == 1234.5


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
