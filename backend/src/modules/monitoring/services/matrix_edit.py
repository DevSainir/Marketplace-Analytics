"""Apply a single user cell-edit to the matrix input working copy.

The monitoring table is edited like a spreadsheet: the user may type into any
*editable* cell, and dependent cells recompute. Because the matrix is derived
from a small set of input facts (:class:`MatrixBaseState`), an edit is resolved
here — on the backend, the single source of formula truth — by mutating the
right input(s), after which :func:`build_matrix_from_base` re-derives everything.

Two kinds of edit:

* **Input cell** (e.g. «Показы», «Затраты»): the input is set directly.
* **Derived cell** (e.g. «CTR», «Конверсия в заказ»): its formula is inverted
  to back-solve exactly one input, holding the others fixed — the convention is
  *solve the numerator, hold the denominator* (editing ``orders/carts`` changes
  ``orders``). Cross-column special cases: «Доля трафика» redistributes this
  bucket's views against the other buckets; «Органика» solves the funnel input
  holding the advertising side fixed.

Cells with no unique inverse (cross-bucket roll-ups in «Общая», the «Органика»
difference beyond its counts, the lagged «Процент выкупа», the legacy
«Каталог» zone, and «—» cells with no value) are read-only and rejected.
"""

from __future__ import annotations

from datetime import date

from src.core.exceptions import ValidationError
from src.modules.monitoring.schemas.matrix import (
    MATRIX_AD_BUCKETS,
    MatrixBaseState,
    MatrixCellEdit,
    MatrixDayBase,
)
from src.modules.monitoring.services.matrix import _day_ad_from_base


def _count(value: float) -> int:
    """Coerce a solved value to a non-negative integer count."""
    return max(0, round(value))


def _money(value: float) -> float:
    """Coerce a solved value to non-negative rubles (2 decimals)."""
    return max(0.0, round(float(value), 2))


def _readonly(bucket: str, metric: str) -> ValidationError:
    """Build the error raised when a non-editable cell is targeted."""
    return ValidationError(f"Cell '{metric}' in column '{bucket}' is not editable.")


def apply_edit(base: MatrixBaseState, edit: MatrixCellEdit) -> MatrixBaseState:
    """Return a copy of ``base`` with one cell-edit applied to its inputs.

    Args:
        base: The current input working copy.
        edit: The cell the user changed (day, bucket, metric, new value).

    Returns:
        A new :class:`MatrixBaseState` with the edit resolved into its inputs;
        pass it to :func:`build_matrix_from_base` to get the recomputed matrix.

    Raises:
        ValidationError: If the day is unknown, or the cell is read-only /
            cannot be uniquely inverted.
    """
    new = base.model_copy(deep=True)
    day = _find_day(new, edit.day)
    if edit.bucket in MATRIX_AD_BUCKETS:
        _edit_ad_bucket(day, edit.bucket, edit.metric, edit.value)
    elif edit.bucket == "total":
        _edit_total(day, edit.metric, edit.value)
    elif edit.bucket == "organic":
        _edit_organic(day, edit.metric, edit.value)
    else:  # uni_catalog or an unknown bucket
        raise _readonly(edit.bucket, edit.metric)
    return new


def _find_day(base: MatrixBaseState, day: date) -> MatrixDayBase:
    """Return the working-copy day matching ``day`` (or raise)."""
    for candidate in base.days:
        if candidate.day == day:
            return candidate
    raise ValidationError(f"Day {day.isoformat()} is not in the current window.")


def _edit_ad_bucket(day: MatrixDayBase, bucket: str, metric: str, value: float) -> None:
    """Resolve an edit in one of the four advertising bucket columns."""
    b = day.buckets.get(bucket)
    if b is None:
        # The cell renders «—» (this bucket delivered nothing that day).
        raise ValidationError(f"No advertising in '{bucket}' on {day.day.isoformat()} to edit.")
    match metric:
        case "views":
            b.views = _count(value)
        case "clicks":
            b.clicks = _count(value)
        case "carts":
            b.add_to_cart = _count(value)
        case "spend":
            b.spend = _money(value)
        case "orders":
            b.orders = _count(value)
        case "order_sum":
            if b.order_sum is None:
                raise _readonly(bucket, metric)  # tainted split zone → «—»
            b.order_sum = _money(value)
        # Derived: solve the numerator, hold the denominator.
        case "ctr":  # clicks / views * 100
            b.clicks = _count(value / 100 * b.views)
        case "cpm":  # spend / views * 1000
            b.spend = _money(value / 1000 * b.views)
        case "cpc":  # spend / clicks
            b.spend = _money(value * b.clicks)
        case "cart_conversion":  # add_to_cart / clicks * 100
            b.add_to_cart = _count(value / 100 * b.clicks)
        case "order_conversion":  # orders / add_to_cart * 100
            b.orders = _count(value / 100 * b.add_to_cart)
        case "cost_per_order":  # spend / orders
            b.spend = _money(value * b.orders)
        case "cost_per_cart":  # spend / add_to_cart
            b.spend = _money(value * b.add_to_cart)
        case "drr_orders":  # spend / order_sum * 100
            if not b.order_sum:
                raise _readonly(bucket, metric)  # order revenue is «—» here
            b.spend = _money(value / 100 * b.order_sum)
        case "traffic_share":
            _solve_traffic_share(day, bucket, value)
        case _:  # drr_sales, buyout_sum, buyout_percent, …
            raise _readonly(bucket, metric)


def _solve_traffic_share(day: MatrixDayBase, bucket: str, value: float) -> None:
    """Set a bucket's views so its share WITHIN ITS BID TYPE equals ``value``.

    «Доля трафика» is normalized per bid type (Единая / Ручной), so only the
    other buckets OF THE SAME TYPE are the denominator. Holding them fixed:
    ``share = v / (others + v)`` ⇒ ``v = others * f / (1 - f)`` with
    ``f = value / 100``; the other same-type buckets' shares then recompute.
    """
    prefix = "uni_" if bucket.startswith("uni_") else "manual_"
    b = day.buckets[bucket]
    others = sum(bb.views for name, bb in day.buckets.items() if name.startswith(prefix)) - b.views
    fraction = value / 100
    if others <= 0 or fraction <= 0 or fraction >= 1:
        # Nothing to redistribute against (the only bucket of its type is always
        # 100%), or an unreachable 0%/100% target.
        raise ValidationError(
            "«Доля трафика» can only be set when another campaign of the same "
            "type has views and the target is strictly between 0% and 100%."
        )
    b.views = _count(others * fraction / (1 - fraction))


def _edit_total(day: MatrixDayBase, metric: str, value: float) -> None:
    """Resolve an edit in the «Общая» column (funnel-backed cells only).

    Prices are editable inputs; «Заказы, ₽»/«Выкупы, ₽»/«СПП» are now DERIVED
    (``count x seller_price`` and the СПП ratio) and therefore read-only.
    """
    f = day.funnel
    if f is None:
        raise ValidationError(f"No funnel data on {day.day.isoformat()} to edit.")
    match metric:
        case "clicks":
            f.open_count = _count(value)
        case "carts":
            f.cart_count = _count(value)
        case "orders":
            f.order_count = _count(value)
        case "seller_price":
            f.seller_price = _money(value)
        case "customer_price":
            f.customer_price = _money(value)
        case "cart_conversion":  # cart_count / open_count * 100
            f.cart_count = _count(value / 100 * f.open_count)
        case "order_conversion":  # order_count / cart_count * 100
            f.order_count = _count(value / 100 * f.cart_count)
        case _:
            # order_sum/buyout_sum/spp derive from the prices (read-only);
            # spend/views/cpc/cost_*/drr_* are cross-bucket ad roll-ups with no
            # unique back-distribution; buyout_percent is a lagged window.
            raise _readonly("total", metric)


def _edit_organic(day: MatrixDayBase, metric: str, value: float) -> None:
    """Resolve an edit in the «Органика» column (общая - реклама).

    Organic = funnel - advertising. Holding the advertising side fixed, an edit
    solves the funnel input: ``funnel = organic + ad``.
    """
    f = day.funnel
    if f is None:
        raise ValidationError(f"No funnel data on {day.day.isoformat()} to edit.")
    day_ad = _day_ad_from_base(day)
    match metric:
        case "clicks":
            f.open_count = _count(value + (day_ad.clicks if day_ad else 0))
        case "carts":
            f.cart_count = _count(value + (day_ad.add_to_cart if day_ad else 0))
        case "orders":
            f.order_count = _count(value + (day_ad.orders if day_ad else 0))
        case _:
            raise _readonly("organic", metric)
