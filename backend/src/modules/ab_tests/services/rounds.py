"""Per-lap arithmetic: who won each round, and how far behind the rest were.

A rotation that cycles produces a second kind of answer the single-lap version
could not. Totals across the whole test say which photo earned the most; rounds
say how *often* it did. Those come apart exactly when they matter — one lap that
happened to run during a promotion can carry a photo's totals while it lost
every other lap it played.

Three columns come out of here, and each one exists because the other two
mislead on their own:

* **Побед в раундах** — laps in which this photo had the best CTR. Robust: a
  freak lap is one vote, not a multiplier.
* **Отклонение CTR от лучшего** — the gap in percentage points. What the numbers
  literally differ by.
* **Результат** — that same gap relative to the leader. «-51 %» means half the
  click-through, which is the sentence a seller can act on; 1.25 pp is not.

A window belongs to the lap that was running when it closed, which is why the
exposures are needed here at all: the windows table knows which photo earned the
traffic, and only the exposure log knows which lap that was.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.modules.ab_tests.models import VariantExposure, VariantStatWindow

#: Percentages are reported to two places, like every other ratio in the module.
_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class RoundStanding:
    """What one photo did across the laps it played."""

    #: Laps this photo was dealt in at all.
    rounds_played: int
    #: Laps in which it had the best click-through of anyone measured.
    rounds_won: int


def _ctr(views: int, clicks: int) -> Decimal | None:
    """Click-through as a percentage, or ``None`` with no impressions.

    Zero impressions is «not measured», not «0 %». A photo that has not been
    seen has not failed to be clicked.
    """
    if views <= 0:
        return None
    return (Decimal(clicks) * 100 / Decimal(views)).quantize(_QUANT)


def _round_of(window: VariantStatWindow, exposures: Sequence[VariantExposure]) -> int | None:
    """Which lap a window's traffic belongs to.

    Matched on the exposure that was open when the window closed, rather than
    when it opened: the poller closes a window and swaps in the same pass, so
    the boundary belongs to the turn that has just ended.

    Args:
        window: One recorded polling interval.
        exposures: The test's exposure log.

    Returns:
        The lap number, or ``None`` for a window with no exposure covering it —
        which should not happen, and is dropped rather than guessed.
    """
    for exposure in exposures:
        if exposure.variant_id != window.variant_id:
            continue
        if exposure.activated_at > window.window_end:
            continue
        if exposure.deactivated_at is not None and exposure.deactivated_at < window.window_end:
            continue
        return exposure.round_number
    return None


def standings(
    *,
    variant_ids: Sequence[uuid.UUID],
    windows: Sequence[VariantStatWindow],
    exposures: Sequence[VariantExposure],
) -> dict[uuid.UUID, RoundStanding]:
    """Count laps played and laps won, per photo.

    A lap is won by the best measured CTR in it. Ties give the win to nobody
    rather than to everybody: two photos that performed identically did not each
    beat the other, and inflating both counts would make «побед» stop summing to
    the number of laps.

    Args:
        variant_ids: Every photo in the test, including excluded ones — they
            keep the laps they already played.
        windows: Every recorded interval of the test.
        exposures: The test's exposure log, which carries the lap numbers.

    Returns:
        One standing per variant id, zeroed for photos that never ran.
    """
    per_round: dict[int, dict[uuid.UUID, tuple[int, int]]] = {}
    played: dict[uuid.UUID, set[int]] = {vid: set() for vid in variant_ids}

    for exposure in exposures:
        if exposure.variant_id in played:
            played[exposure.variant_id].add(exposure.round_number)

    for window in windows:
        lap = _round_of(window, exposures)
        if lap is None:
            continue
        views, clicks = per_round.setdefault(lap, {}).get(window.variant_id, (0, 0))
        per_round[lap][window.variant_id] = (views + window.views, clicks + window.clicks)

    won: dict[uuid.UUID, int] = dict.fromkeys(variant_ids, 0)
    for contenders in per_round.values():
        ranked = [
            (variant_id, ctr)
            for variant_id, (views, clicks) in contenders.items()
            if (ctr := _ctr(views, clicks)) is not None
        ]
        if not ranked:
            continue
        best = max(ctr for _, ctr in ranked)
        winners = [variant_id for variant_id, ctr in ranked if ctr == best]
        if len(winners) == 1 and winners[0] in won:
            won[winners[0]] += 1

    return {
        variant_id: RoundStanding(
            rounds_played=len(played.get(variant_id, set())), rounds_won=won[variant_id]
        )
        for variant_id in variant_ids
    }


def gap_to_best(ctr: Decimal | None, best: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """How far behind the leader one photo's click-through is.

    Args:
        ctr: This photo's click-through, or ``None`` if unmeasured.
        best: The best click-through in the test, or ``None`` if nothing is.

    Returns:
        ``(absolute gap in percentage points, relative gap in percent)``. The
        leader gets ``(0, 0)`` rather than ``None``: it is measured, and it is
        exactly zero behind itself. Both are ``None`` when either side is
        unmeasured, because «behind by an unknown amount» is not a number.
    """
    if ctr is None or best is None or best <= 0:
        return None, None
    absolute = (best - ctr).quantize(_QUANT)
    relative = ((ctr - best) * 100 / best).quantize(_QUANT)
    return absolute, relative


__all__ = ["RoundStanding", "gap_to_best", "standings"]
