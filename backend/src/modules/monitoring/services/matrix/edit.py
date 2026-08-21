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
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixCellEdit,
    MatrixDayBase,
    bucket_traffic_type,
)
from src.modules.monitoring.services.matrix.assoc import _allocate_counts
from src.modules.monitoring.services.matrix.build import _day_ad_from_base
from src.modules.monitoring.services.matrix.pricing import ad_order_sum


def _count(value: float) -> int:
    """Coerce a solved value to a non-negative integer count."""
    return max(0, round(value))


def _money(value: float) -> float:
    """Coerce a solved value to non-negative rubles (2 decimals)."""
    return max(0.0, round(float(value), 2))


def _percent(value: float) -> float:
    """Coerce a solved value to a non-negative percentage (2 decimals)."""
    return max(0.0, round(float(value), 2))


def _readonly(bucket: str, metric: str) -> ValidationError:
    """Build the error raised when a non-editable cell is targeted."""
    return ValidationError(f"Cell '{metric}' in column '{bucket}' is not editable.")


def apply_edit(
    base: MatrixBaseState, edit: MatrixCellEdit, *, viewed_nm_id: int | None = None
) -> MatrixBaseState:
    """Return a copy of ``base`` with one cell-edit applied.

    EVERY cell is editable. An **invertible input** cell (e.g. «Показы»,
    «Конверсия в заказ») back-solves an input fact so dependent cells recompute
    (dynamic). Any other cell — a cross-bucket rollup, a derived ratio, the
    empty «Каталог» zone — records a **display override**
    (:attr:`MatrixDayBase.cell_overrides`) shown verbatim after the formulas.

    Args:
        base: The current input working copy.
        edit: The cell the user changed (day, bucket, metric, new value).
        viewed_nm_id: The SKU on screen. Editing an ad zone's carts/orders
            moves its per-variant breakdown with it (see
            :func:`_set_ad_metric`), which needs to know which row of that
            breakdown is this SKU's own.

    Returns:
        A new :class:`MatrixBaseState` with the edit applied; pass it to
        :func:`build_matrix_from_base` to get the recomputed matrix.

    Raises:
        ValidationError: If the day is not in the current window.
    """
    new = base.model_copy(deep=True)
    day = _find_day(new, edit.day)
    key = f"{edit.bucket}:{edit.metric}"
    try:
        _apply_input_edit(day, edit, viewed_nm_id)
    except ValidationError:
        # Non-invertible cell (read-only formula, tainted zone, empty «Каталог»,
        # a count with no funnel row) → store a direct display override so the
        # cell is still editable. Shown verbatim in build_matrix_from_base.
        day.cell_overrides[key] = round(float(edit.value), 2)
    else:
        # A successful dynamic edit supersedes any stale display override on the
        # same cell (e.g. a count edited on a day that later gained a funnel row).
        day.cell_overrides.pop(key, None)
    return new


def _apply_input_edit(
    day: MatrixDayBase, edit: MatrixCellEdit, viewed_nm_id: int | None = None
) -> None:
    """Resolve the edit as an invertible input, or raise for a non-invertible cell."""
    if edit.bucket in MATRIX_AD_BUCKETS:
        _edit_ad_bucket(day, edit.bucket, edit.metric, edit.value, viewed_nm_id)
    elif edit.bucket == "total":
        _edit_total(day, edit.metric, edit.value)
    elif edit.bucket == "organic":
        _edit_organic(day, edit.metric, edit.value)
    else:  # uni_catalog or an unknown bucket — no unique inverse
        raise _readonly(edit.bucket, edit.metric)


def _find_day(base: MatrixBaseState, day: date) -> MatrixDayBase:
    """Return the working-copy day matching ``day`` (or raise)."""
    for candidate in base.days:
        if candidate.day == day:
            return candidate
    raise ValidationError(f"Day {day.isoformat()} is not in the current window.")


#: The carts/orders fields, whose edit also has a per-variant breakdown to keep
#: in step (every other ad metric is a plain number).
_BREAKDOWN_FIELDS: frozenset[str] = frozenset({"add_to_cart", "orders"})


def _set_ad_metric(
    bucket: MatrixAdBucketBase, field: str, value: float, viewed_nm_id: int | None = None
) -> None:
    """Set an ad cell's CAMPAIGN metric, moving the card's own share with it.

    An advertising cell states what the кампания did, so that is what a typed
    number sets. The rest of the campaign is harvested fact the edit has no
    claim on — the other cards' spend, the other variants' conversions — so the
    VIEWED card's own share absorbs the whole delta, which keeps «Общая» and
    «Органика» (built from that share) in step with the correction.

    The share floors at zero and caps at the new total: correcting a cell to
    less than the rest of the campaign holds leaves the card with none of it.
    For carts/orders that also means the hover's rows have to shrink, or the
    breakdown would list more than the cell above it.

    Args:
        bucket: The ad bucket being edited.
        field: The metric field on the bucket (and on its ``sku`` share).
        value: The new value for the whole campaign.
        viewed_nm_id: The SKU on screen; without it the per-variant rows cannot
            be identified and only the counts move.
    """
    if field == "spend":
        spend = _money(value)
        # The card's own share moves by the same delta, floored/capped as below.
        own_spend = min(max(bucket.sku.spend + spend - bucket.spend, 0.0), spend)
        bucket.spend = spend
        bucket.sku.spend = _money(own_spend)
        return
    count = _count(value)
    own = _count(min(max(getattr(bucket.sku, field) + count - getattr(bucket, field), 0), count))
    setattr(bucket, field, count)
    setattr(bucket.sku, field, own)

    if field not in _BREAKDOWN_FIELDS or viewed_nm_id is None or not bucket.assoc_skus:
        return
    _keep_breakdown_summing(bucket, field, own, count, viewed_nm_id)


def _keep_breakdown_summing(
    bucket: MatrixAdBucketBase, field: str, own: int, total: int, viewed_nm_id: int
) -> None:
    """Rewrite the per-variant rows so they still add up to the edited cell."""
    others = {
        sku.nm_id: getattr(sku, field) for sku in bucket.assoc_skus if sku.nm_id != viewed_nm_id
    }
    if own == 0 and sum(others.values()) > total:
        # The typed total no longer covers the other variants: scale them down
        # proportionally rather than let the hover exceed its own cell.
        allocated = _allocate_counts(others, total)
        for sku in bucket.assoc_skus:
            if sku.nm_id != viewed_nm_id:
                setattr(sku, field, allocated.get(sku.nm_id, 0))
    for sku in bucket.assoc_skus:
        if sku.nm_id == viewed_nm_id:
            setattr(sku, field, own)
            return
    # The SKU had none of this metric before, so it has no row yet.
    if own > 0:
        bucket.assoc_skus.append(AssocSkuCount(nm_id=viewed_nm_id, **{field: own}))


def _edit_ad_bucket(
    day: MatrixDayBase, bucket: str, metric: str, value: float, viewed_nm_id: int | None = None
) -> None:
    """Resolve an edit in one of the four advertising bucket columns."""
    b = day.buckets.get(bucket)
    if b is None:
        # The cell renders «—» (this bucket delivered nothing that day).
        raise ValidationError(f"No advertising in '{bucket}' on {day.day.isoformat()} to edit.")
    match metric:
        case "views":
            _set_ad_metric(b, "views", value)
        case "clicks":
            _set_ad_metric(b, "clicks", value)
        case "carts":
            _set_ad_metric(b, "add_to_cart", value, viewed_nm_id)
        case "spend":
            _set_ad_metric(b, "spend", value)
        case "orders":
            _set_ad_metric(b, "orders", value, viewed_nm_id)
        case "order_sum":  # orders x seller_price -> solve the orders count
            # The displayed revenue is DERIVED from the campaign's orders, so
            # writing `b.order_sum` here would change nothing on screen.
            price = day.funnel.seller_price if day.funnel else None
            if not price:
                raise _readonly(bucket, metric)  # unpriced day → «—»
            _set_ad_metric(b, "orders", value / price, viewed_nm_id)
        # Derived: solve the numerator, hold the denominator.
        case "ctr":  # clicks / views * 100
            _set_ad_metric(b, "clicks", value / 100 * b.views)
        case "cpm":  # spend / views * 1000
            _set_ad_metric(b, "spend", value / 1000 * b.views)
        case "cpc":  # spend / clicks
            _set_ad_metric(b, "spend", value * b.clicks)
        case "cart_conversion":  # add_to_cart / clicks * 100
            _set_ad_metric(b, "add_to_cart", value / 100 * b.clicks, viewed_nm_id)
        case "order_conversion":  # orders / add_to_cart * 100
            _set_ad_metric(b, "orders", value / 100 * b.add_to_cart, viewed_nm_id)
        case "cost_per_order":  # spend / orders
            _set_ad_metric(b, "spend", value * b.orders)
        case "cost_per_cart":  # spend / add_to_cart
            _set_ad_metric(b, "spend", value * b.add_to_cart)
        case "drr_orders":  # spend / (orders x seller_price) * 100
            order_sum = ad_order_sum(b.orders, day.funnel)
            if not order_sum:
                raise _readonly(bucket, metric)  # order revenue is «—» here
            _set_ad_metric(b, "spend", value / 100 * order_sum)
        case "traffic_share":
            _solve_traffic_share(day, bucket, value)
        case _:  # drr_sales, buyout_sum, buyout_percent, …
            # «ДРР от продаж» is deliberately not inverted: it is ONE merged
            # cell over a campaign's zones, so moving a single zone's spend
            # would not reproduce the typed number. It takes a display
            # override instead (shown verbatim, which is what typing means).
            raise _readonly(bucket, metric)


def _solve_traffic_share(day: MatrixDayBase, bucket: str, value: float) -> None:
    """Set a bucket's views so its share WITHIN ITS TRAFFIC TYPE equals ``value``.

    «Доля трафика» is normalized per «тип получения трафика» (Единая / Ручной /
    CPC), so only the other buckets OF THE SAME TYPE are the denominator.
    Holding them fixed: ``share = v / (others + v)`` ⇒
    ``v = others * f / (1 - f)`` with ``f = value / 100``; the other same-type
    buckets' shares then recompute.
    """
    traffic_type = bucket_traffic_type(bucket)
    b = day.buckets[bucket]
    others = (
        sum(
            bb.views
            for name, bb in day.buckets.items()
            if bucket_traffic_type(name) == traffic_type
        )
        - b.views
    )
    fraction = value / 100
    if others <= 0 or fraction <= 0 or fraction >= 1:
        # Nothing to redistribute against (the only bucket of its type is always
        # 100%), or an unreachable 0%/100% target.
        raise ValidationError(
            "«Доля трафика» can only be set when another campaign of the same "
            "type has views and the target is strictly between 0% and 100%."
        )
    _set_ad_metric(b, "views", others * fraction / (1 - fraction))


def _edit_total(day: MatrixDayBase, metric: str, value: float) -> None:
    """Resolve an edit in the «Общая» column (funnel-backed cells only).

    Prices and counts are the inputs; «Выкупы, ₽»/«СПП» derive from them.
    «Заказы, ₽» is derived too, but invertibly — it solves the order COUNT
    (the price is never rewritten by another cell's edit).
    """
    # «Процент выкупа» is a HARVESTED fact, not a formula: the cohort pass
    # reads it from WB's period aggregate. So it is a plain input here, and
    # editing it recomputes «Выкупы, ₽» (in «Общая» and in every ad zone) plus
    # both ДРР rows. Handled before the funnel guard — a day can carry a buyout
    # percent without a funnel row of its own.
    if metric == "buyout_percent":
        day.lagged_buyout_percent = _percent(value)
        return

    f = day.funnel
    if f is None:
        raise ValidationError(f"No funnel data on {day.day.isoformat()} to edit.")
    # A price-only day (funnel not served yet): counts are not facts there —
    # only the prices are editable.
    counts_editable = f.has_funnel
    match metric:
        case "clicks" if counts_editable:
            f.open_count = _count(value)
        case "carts" if counts_editable:
            f.cart_count = _count(value)
        case "orders" if counts_editable:
            f.order_count = _count(value)
        case "seller_price":
            f.seller_price = _money(value)
        case "customer_price":
            f.customer_price = _money(value)
        case "cart_conversion" if counts_editable:  # cart_count / open_count * 100
            f.cart_count = _count(value / 100 * f.open_count)
        case "order_conversion" if counts_editable:  # order_count / cart_count * 100
            f.order_count = _count(value / 100 * f.cart_count)
        case "order_sum" if counts_editable:  # order_count x seller_price
            # Solve the COUNT, never the price: a price is a snapshot of what
            # the SKU cost that day, and no other cell's edit may rewrite it.
            # The advertising zones keep their own orders — this is the
            # SKU-wide funnel count, so «Органика» absorbs the difference.
            if not f.seller_price:
                raise _readonly("total", metric)  # unpriced day → «—»
            f.order_count = _count(value / f.seller_price)
        case _:
            # buyout_sum/spp derive from the prices and counts (read-only);
            # spend/views/cpc/cost_*/drr_* are cross-bucket ad roll-ups with no
            # unique back-distribution.
            raise _readonly("total", metric)


def _edit_organic(day: MatrixDayBase, metric: str, value: float) -> None:
    """Resolve an edit in the «Органика» column (общая - реклама).

    Organic = funnel - advertising. Holding the advertising side fixed, an edit
    solves the funnel input: ``funnel = organic + ad``.
    """
    f = day.funnel
    if f is None or not f.has_funnel:
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
