"""Apportion associated-variant conversions across a split campaign-day.

WB reports «ассоциированные конверсии» only at campaign level, so when a
campaign-day is split across display zones the associated variants' counts have
no exact zone attribution. The helpers here allocate them proportionally while
keeping every leg's rows summing exactly to the leg totals.
"""

from __future__ import annotations

from collections import defaultdict


def _allocate_assoc(extra: int, s_metric: int, total_metric: int, view_share: float) -> int:
    """Portion of the associative EXTRA conversions allocated to the search leg.

    WB reports associated-variant conversions only at campaign level (the
    normquery search slice tracks the advertised SKU's own conversions — see
    the live data: search carts never exceed the SKU's), so a split
    campaign-day's extra has no exact zone attribution. It is apportioned by
    the SKU's own zone split of the same metric — the best available estimator
    of where the delivering clicks were — falling back to the view share when
    the SKU itself had none of the metric. Leg sums stay exact by construction
    (shelves takes the remainder).
    """
    share = s_metric / total_metric if total_metric > 0 else view_share
    return min(extra, max(0, round(extra * share)))


def _allocate_counts(counts: dict[int, int], target: int) -> dict[int, int]:
    """Distribute ``target`` across ``counts`` in proportion, summing exactly.

    Largest-remainder: floor every share, then hand the rounding slack to the
    variants that lost the most to the floor. Summing exactly is what lets the
    hover's rows add up to the number in the cell.
    """
    pool = sum(counts.values())
    if pool <= 0 or target <= 0:
        return {}
    shares = {nm: target * count / pool for nm, count in counts.items()}
    allocated = {nm: int(share) for nm, share in shares.items()}
    slack = target - sum(allocated.values())
    ranked = sorted(counts, key=lambda nm: (-(shares[nm] - allocated[nm]), -counts[nm], nm))
    for nm in ranked[:slack]:
        allocated[nm] += 1
    return {nm: count for nm, count in allocated.items() if count > 0}


def _split_assoc_skus(
    skus: dict[int, tuple[int, int]],
    *,
    viewed_nm: int,
    search_own: tuple[int, int],
    search_extra: tuple[int, int],
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Split a campaign-day's per-variant counts into (search, remainder) legs.

    The viewed SKU's own counts split exactly — WB's normquery slice states how
    many of ITS conversions came from search. Only the associated variants'
    counts are apportioned, by the same share the aggregate extra uses, so both
    legs' rows sum to the leg totals the zone split computed.

    Args:
        skus: The campaign-day's counts per variant, ``nm -> (carts, orders)``.
        viewed_nm: The SKU being analyzed.
        search_own: The viewed SKU's ``(carts, orders)`` in the search zone.
        search_extra: The associated variants' ``(carts, orders)`` allocated to
            the search zone.

    Returns:
        The ``(search, remainder)`` per-variant maps.
    """
    search: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for index in (0, 1):
        others = {nm: c[index] for nm, c in skus.items() if nm != viewed_nm and c[index] > 0}
        for nm, count in _allocate_counts(others, search_extra[index]).items():
            search[nm][index] = count
    for index in (0, 1):
        if search_own[index] > 0:
            search[viewed_nm][index] = search_own[index]

    search_map = {nm: (c[0], c[1]) for nm, c in search.items() if c[0] > 0 or c[1] > 0}
    remainder: dict[int, tuple[int, int]] = {}
    for nm, (carts, orders) in skus.items():
        taken_carts, taken_orders = search_map.get(nm, (0, 0))
        left = (carts - taken_carts, orders - taken_orders)
        if left[0] > 0 or left[1] > 0:
            remainder[nm] = left
    return search_map, remainder
