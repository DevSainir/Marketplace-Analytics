"""Per-lap arithmetic: how many laps each photo played, and how far behind it is.

Two columns come out of here:

** **"Rounds"** — laps this photo was dealt in. What keeps a photo that has run
  once from reading the same as one that has run fifteen times.
** **"CTR gap to best"** / **"Result"** — the gap to the leader in
  percentage points, and the same gap relative to the leader. "-51%" means
  half the click-through, which is the sentence a seller can act on; 1.25 pp is
  what the numbers literally differ by.

There used to be a third, "Rounds won" — laps in which the photo had the
best CTR. It was removed on 2026-09-28 at the owner's request: it did not earn
its row.

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
    played_from_windows: bool = False,
) -> dict[uuid.UUID, RoundStanding]:
    """Count the laps each photo played.

    Args:
        variant_ids: Every photo in the test, including excluded ones — they
            keep the laps they already played.
        windows: Every recorded interval of the test.
        exposures: The test's exposure log, which carries the lap numbers.
        played_from_windows: Count a lap as played only where the photo has a
            window in it, rather than wherever it had a turn. False for the
            whole test, where a turn with no traffic still happened; True when
            the windows have been filtered to ONE campaign, where "rounds" has
            to mean "laps of this ad campaign" — a campaign switched off on lap four did
            not play laps five to ten, and saying it did would put a zero in
            every one of them.

    Returns:
        One standing per variant id, zeroed for photos that never ran.
    """
    played: dict[uuid.UUID, set[int]] = {vid: set() for vid in variant_ids}

    if played_from_windows:
        for window in windows:
            if window.variant_id not in played:
                continue
            lap = _round_of(window, exposures)
            if lap is not None:
                played[window.variant_id].add(lap)
    else:
        for exposure in exposures:
            if exposure.variant_id in played:
                played[exposure.variant_id].add(exposure.round_number)

    return {
        variant_id: RoundStanding(rounds_played=len(played[variant_id]))
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
