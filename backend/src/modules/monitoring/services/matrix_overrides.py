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
    MatrixBaseState,
)

#: Editable input fields of an advertising bucket.
_AD_FIELDS: tuple[str, ...] = ("views", "clicks", "add_to_cart", "spend", "orders", "order_sum")
#: Editable input fields of the organic funnel (behind «Общая»). The ₽ volumes
#: and СПП are derived from ``seller_price``/``customer_price`` (not stored).
_FUNNEL_FIELDS: tuple[str, ...] = (
    "open_count",
    "cart_count",
    "order_count",
    "seller_price",
    "customer_price",
)
#: The synthetic bucket name under which funnel inputs are stored.
_FUNNEL_BUCKET = "funnel"
#: Fields that are integer counts (stored as numeric, coerced back on overlay).
_INT_FIELDS: frozenset[str] = frozenset(
    {"views", "clicks", "add_to_cart", "orders", "open_count", "cart_count", "order_count"}
)


def _coerce(field: str, value: float) -> int | float:
    """Coerce a stored numeric override back to the field's native type."""
    return round(value) if field in _INT_FIELDS else round(float(value), 2)


def overlay_overrides(base: MatrixBaseState, overrides: list[MatrixOverride]) -> None:
    """Apply stored overrides onto a fact-derived base state, in place.

    Missing targets (a bucket that no longer delivered, an unknown field) are
    skipped defensively — overrides are cleared on every WB refresh, so they
    normally stay consistent with the facts they were derived from.

    Args:
        base: The fact-derived working copy to mutate.
        overrides: The SKU's stored override rows for the window.
    """
    by_day = {day.day: day for day in base.days}
    for override in overrides:
        day = by_day.get(override.stat_date)
        if day is None:
            continue
        value = _coerce(override.field, float(override.value))
        if override.bucket == _FUNNEL_BUCKET:
            if day.funnel is not None and override.field in _FUNNEL_FIELDS:
                setattr(day.funnel, override.field, value)
        elif override.bucket in MATRIX_AD_BUCKETS and override.field in _AD_FIELDS:
            bucket = day.buckets.get(override.bucket)
            if bucket is not None:
                setattr(bucket, override.field, value)


def _differs(working: float | None, fact: float | None) -> bool:
    """Whether an input value was edited (2-decimal comparison; ``None``-safe)."""
    if working is None or fact is None:
        return False  # tainted / read-only inputs are never overridable
    return round(working, 2) != round(fact, 2)


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
    return rows
