"""Map manual matrix edits between the base working copy and stored overrides.

Overrides are persisted at the input-fact grain (:class:`MatrixOverride`): one
row per changed input field. This module is the single place that knows which
fields are editable and how a ``bucket``/``field`` pair maps onto the
:class:`MatrixBaseState` — used to *overlay* stored edits on read and to *diff*
a saved working copy back into override rows on write.
"""

from __future__ import annotations

from src.modules.monitoring.models import MatrixOverride
from src.modules.monitoring.schemas.matrix import (
    MATRIX_AD_BUCKETS,
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixBaseState,
)

#: Editable input fields of an advertising bucket — the campaign's own numbers.
_AD_FIELDS: tuple[str, ...] = (
    "views",
    "clicks",
    "add_to_cart",
    "spend",
    "orders",
    "order_sum",
)
#: The viewed card's share of those same fields, stored under a ``sku.`` prefix.
#: It rides along because an edit moves both sides (see
#: ``matrix.edit._set_ad_metric``): persisting only the campaign's would leave
#: the reloaded «Общая»/«Органика» quoting the harvested share against a
#: corrected campaign, and the hover disagreeing with its own cell.
_AD_SKU_PREFIX = "sku."
_AD_SKU_FIELDS: tuple[str, ...] = ("views", "clicks", "add_to_cart", "spend", "orders")
#: Card-share fields whose override must also be mirrored onto the viewed SKU's
#: row of the per-variant breakdown (that row IS this SKU's own count).
_VIEWED_ROW_FIELDS: frozenset[str] = frozenset({"add_to_cart", "orders"})
#: Editable input fields of the organic funnel (behind «Общая»). The ₽ volumes
#: and SPP are derived from ``seller_price``/``customer_price`` (not stored).
_FUNNEL_FIELDS: tuple[str, ...] = (
    "open_count",
    "cart_count",
    "order_count",
    "seller_price",
    "customer_price",
)
#: The synthetic bucket name under which funnel inputs are stored.
_FUNNEL_BUCKET = "funnel"
#: The synthetic bucket name for DAY-level inputs (no bucket of their own).
_DAY_BUCKET = "day"
#: Editable day-level inputs. «Процент выкупа» is harvested from WB's period
#: aggregate, so it is a fact a manager may correct — and everything derived
#: from it («Выкупы, ₽», both DRR rows) recomputes.
_DAY_FIELDS: tuple[str, ...] = ("lagged_buyout_percent",)
#: The synthetic bucket name under which DISPLAY overrides are stored; the
#: ``field`` is then the ``"<bucket>:<metric>"`` cell key.
_CELL_BUCKET = "cell"
#: Fields that are integer counts (stored as numeric, coerced back on overlay).
_INT_FIELDS: frozenset[str] = frozenset(
    {
        "views",
        "clicks",
        "add_to_cart",
        "orders",
        "open_count",
        "cart_count",
        "order_count",
        "sku.views",
        "sku.clicks",
        "sku.add_to_cart",
        "sku.orders",
    }
)


def _coerce(field: str, value: float) -> int | float:
    """Coerce a stored numeric override back to the field's native type."""
    return round(value) if field in _INT_FIELDS else round(float(value), 2)


def overlay_overrides(
    base: MatrixBaseState, overrides: list[MatrixOverride], *, nm_id: int | None = None
) -> None:
    """Apply stored overrides onto a fact-derived base state, in place.

    Missing targets (a bucket that no longer delivered, an unknown field) are
    skipped defensively — overrides are cleared on every WB refresh, so they
    normally stay consistent with the facts they were derived from.

    Args:
        base: The fact-derived working copy to mutate.
        overrides: The SKU's stored override rows for the window.
        nm_id: The SKU the overrides belong to. Restoring an edited carts/orders
            count also restores it onto that SKU's row of the per-variant
            breakdown, so a reloaded hover still sums to its cell.
    """
    by_day = {day.day: day for day in base.days}
    for override in overrides:
        day = by_day.get(override.stat_date)
        if day is None:
            continue
        if override.bucket == _CELL_BUCKET:
            # Display override: applied to the computed cell, not an input.
            day.cell_overrides[override.field] = round(float(override.value), 2)
            continue
        value = _coerce(override.field, float(override.value))
        if override.bucket == _DAY_BUCKET:
            if override.field in _DAY_FIELDS:
                setattr(day, override.field, value)
        elif override.bucket == _FUNNEL_BUCKET:
            if day.funnel is not None and override.field in _FUNNEL_FIELDS:
                setattr(day.funnel, override.field, value)
        elif override.bucket in MATRIX_AD_BUCKETS:
            bucket = day.buckets.get(override.bucket)
            if bucket is None:
                continue
            if override.field in _AD_FIELDS:
                setattr(bucket, override.field, value)
            elif override.field.startswith(_AD_SKU_PREFIX):
                field = override.field.removeprefix(_AD_SKU_PREFIX)
                if field in _AD_SKU_FIELDS:
                    setattr(bucket.sku, field, value)
                    if nm_id is not None and field in _VIEWED_ROW_FIELDS:
                        _restore_viewed_row(bucket, field, int(value), nm_id)


def _restore_viewed_row(bucket: MatrixAdBucketBase, field: str, value: int, nm_id: int) -> None:
    """Put an overridden own-count back onto the viewed SKU's breakdown row."""
    if not bucket.assoc_skus:
        return
    for sku in bucket.assoc_skus:
        if sku.nm_id == nm_id:
            setattr(sku, field, value)
            return
    if value > 0:
        bucket.assoc_skus.append(AssocSkuCount(nm_id=nm_id, **{field: value}))


def _differs(working: float | None, fact: float | None) -> bool:
    """Whether an input value was edited (2-decimal comparison; ``None``-safe)."""
    if working is None or fact is None:
        return False  # tainted / read-only inputs are never overridable
    return round(working, 2) != round(fact, 2)


def _day_value_differs(working: float | None, fact: float | None) -> bool:
    """Whether a day-level input was edited, INCLUDING onto an absent fact.

    Unlike :func:`_differs`, a ``None`` fact is a real starting point here: WB
    serves no cohort for a day whose deliveries have not matured, and typing a
    «Процент выкупа» there is exactly the correction the manager is making.
    """
    if working is None:
        return False
    return fact is None or round(working, 2) != round(fact, 2)


def diff_to_overrides(
    *, nm_id: int, working: MatrixBaseState, fact: MatrixBaseState
) -> list[dict[str, object]]:
    """Diff an edited working copy against the fact-derived base into override rows.

    Only input fields that actually changed become overrides, so a cell edited
    back to its harvested value persists nothing.

    Args:
        nm_id: WB SKU identifier the overrides belong to.
        working: The saved working copy (from the client).
        fact: The freshly fact-derived base for the same window.

    Returns:
        Column->value mappings ready for ``MatrixOverrideRepository.replace_window``.
    """
    fact_by_day = {day.day: day for day in fact.days}
    rows: list[dict[str, object]] = []
    for w_day in working.days:
        f_day = fact_by_day.get(w_day.day)
        if f_day is None:
            continue
        for name in MATRIX_AD_BUCKETS:
            w_bucket = w_day.buckets.get(name)
            f_bucket = f_day.buckets.get(name)
            if w_bucket is None or f_bucket is None:
                continue
            for field in _AD_FIELDS:
                w_val = getattr(w_bucket, field)
                if _differs(w_val, getattr(f_bucket, field)):
                    rows.append(
                        {
                            "nm_id": nm_id,
                            "stat_date": w_day.day,
                            "bucket": name,
                            "field": field,
                            "value": w_val,
                        }
                    )
            for field in _AD_SKU_FIELDS:
                w_val = getattr(w_bucket.sku, field)
                if _differs(w_val, getattr(f_bucket.sku, field)):
                    rows.append(
                        {
                            "nm_id": nm_id,
                            "stat_date": w_day.day,
                            "bucket": name,
                            "field": f"{_AD_SKU_PREFIX}{field}",
                            "value": w_val,
                        }
                    )
        for field in _DAY_FIELDS:
            w_val = getattr(w_day, field)
            if _day_value_differs(w_val, getattr(f_day, field)):
                rows.append(
                    {
                        "nm_id": nm_id,
                        "stat_date": w_day.day,
                        "bucket": _DAY_BUCKET,
                        "field": field,
                        "value": w_val,
                    }
                )
        if w_day.funnel is not None and f_day.funnel is not None:
            for field in _FUNNEL_FIELDS:
                w_val = getattr(w_day.funnel, field)
                if _differs(w_val, getattr(f_day.funnel, field)):
                    rows.append(
                        {
                            "nm_id": nm_id,
                            "stat_date": w_day.day,
                            "bucket": _FUNNEL_BUCKET,
                            "field": field,
                            "value": w_val,
                        }
                    )
        # Display overrides: the fact base has none, so every working entry is a
        # deliberate manual edit — persist each as a ``cell`` row.
        for cell_key, w_val in w_day.cell_overrides.items():
            rows.append(
                {
                    "nm_id": nm_id,
                    "stat_date": w_day.day,
                    "bucket": _CELL_BUCKET,
                    "field": cell_key,
                    "value": w_val,
                }
            )
    return rows
