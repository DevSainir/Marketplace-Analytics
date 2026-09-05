"""The one place that decides what a valid trigger configuration is.

Both callers live at different layers — the create schema validates a whole body
before anything is persisted, and the settings update validates a partial change
against what is already stored — so the rule sits here rather than in either of
them. Two copies of "which field belongs to which mode" is exactly the kind of
duplication that drifts: the create path would keep refusing a stray field while
the edit path quietly accepted it.

**The rule.** A test rotates either on impressions or on time, never on
"whichever comes first". Sending the other mode's setting is refused rather than
ignored, because a silently dropped field leaves the user believing they
configured something they did not — and because a test measured partly by
audience and partly by clock judges its photos on different exposures, which is
the one thing a budget exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.modules.ab_tests.models import (
    DEFAULT_IMPRESSION_BUDGET,
    DEFAULT_SLOT_MINUTES,
    TriggerMode,
)


@dataclass(frozen=True)
class TriggerSettings:
    """A resolved, self-consistent rotation trigger.

    Both numbers are always populated: the unused one keeps its stored (or
    default) value so switching modes back and forth does not lose what the
    other mode was set to. Only the one named by ``mode`` is ever read by
    :mod:`.rotation`.
    """

    mode: TriggerMode
    impression_budget: int
    slot_minutes: int


def resolve(
    *,
    mode: TriggerMode | None,
    impression_budget: int | None,
    slot_minutes: int | None,
    current: TriggerSettings | None = None,
) -> TriggerSettings:
    """Validate a trigger change and fill in what was not supplied.

    Args:
        mode: The requested mode, or ``None`` to keep the current one.
        impression_budget: Requested budget, or ``None`` to leave it.
        slot_minutes: Requested slot length, or ``None`` to leave it.
        current: What the test is configured with today. ``None`` for a new
            test, which starts from the module defaults.

    Returns:
        The settings to store.

    Raises:
        ValidationError: If the payload carries the setting belonging to the
            mode that will NOT be in force.
    """
    base = current or TriggerSettings(
        mode=TriggerMode.IMPRESSIONS,
        impression_budget=DEFAULT_IMPRESSION_BUDGET,
        slot_minutes=DEFAULT_SLOT_MINUTES,
    )
    effective = mode or base.mode

    if effective is TriggerMode.IMPRESSIONS and slot_minutes is not None:
        raise ValidationError(
            "В режиме «по показам» время на вариант не задаётся — уберите slot_minutes."
        )
    if effective is TriggerMode.TIME and impression_budget is not None:
        raise ValidationError(
            "В режиме «по времени» бюджет показов не задаётся — уберите impression_budget."
        )

    return TriggerSettings(
        mode=effective,
        impression_budget=impression_budget or base.impression_budget,
        slot_minutes=slot_minutes or base.slot_minutes,
    )
