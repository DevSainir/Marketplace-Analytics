"""Unit tests for the trigger configuration rule (services/triggers.py).

One rule, two callers: the create schema validates a whole body, the settings
PATCH validates a partial change against a stored test. It lives in one module
precisely so those two cannot drift — the failure that would produce is the
worst kind, where creating a test refuses a stray field and editing one quietly
accepts it.
"""

from __future__ import annotations

import pytest

from src.core.exceptions import ValidationError
from src.modules.ab_tests.models import (
    DEFAULT_IMPRESSION_BUDGET,
    DEFAULT_SLOT_MINUTES,
    TriggerMode,
)
from src.modules.ab_tests.services.triggers import TriggerSettings, resolve

CURRENT_IMPRESSIONS = TriggerSettings(
    mode=TriggerMode.IMPRESSIONS, impression_budget=2_000, slot_minutes=45
)
CURRENT_TIME = TriggerSettings(mode=TriggerMode.TIME, impression_budget=2_000, slot_minutes=45)


def test_a_new_test_defaults_to_impressions() -> None:
    """With nothing supplied a test counts impressions, not minutes.

    The default is the statistically sound one: every photo gets the same number
    of chances, so a CTR difference is a difference in the photo.
    """
    resolved = resolve(mode=None, impression_budget=None, slot_minutes=None)

    assert resolved.mode is TriggerMode.IMPRESSIONS
    assert resolved.impression_budget == DEFAULT_IMPRESSION_BUDGET
    assert resolved.slot_minutes == DEFAULT_SLOT_MINUTES


def test_the_slot_length_is_refused_in_impressions_mode() -> None:
    """Sending the other mode's setting fails rather than being dropped.

    A silently ignored field leaves the user believing they configured
    something they did not.
    """
    with pytest.raises(ValidationError, match="slot_minutes"):
        resolve(mode=TriggerMode.IMPRESSIONS, impression_budget=5_000, slot_minutes=30)


def test_the_budget_is_refused_in_time_mode() -> None:
    """The same rule in the other direction."""
    with pytest.raises(ValidationError, match="impression_budget"):
        resolve(mode=TriggerMode.TIME, impression_budget=5_000, slot_minutes=30)


def test_a_partial_edit_is_checked_against_the_stored_mode() -> None:
    """Setting minutes on a test that counts impressions is refused.

    The body never names a mode here, so the rule has to resolve one from the
    test itself — this is the case a schema-only check cannot see, and the
    reason the rule takes ``current``.
    """
    with pytest.raises(ValidationError):
        resolve(
            mode=None,
            impression_budget=None,
            slot_minutes=30,
            current=CURRENT_IMPRESSIONS,
        )


def test_changing_only_the_budget_keeps_the_mode_and_the_other_setting() -> None:
    """A partial edit leaves everything it did not mention alone."""
    resolved = resolve(
        mode=None, impression_budget=3_000, slot_minutes=None, current=CURRENT_IMPRESSIONS
    )

    assert resolved.mode is TriggerMode.IMPRESSIONS
    assert resolved.impression_budget == 3_000
    assert resolved.slot_minutes == 45


def test_switching_mode_and_its_setting_together_is_accepted() -> None:
    """The ordinary edit: name the new mode and the number it uses."""
    resolved = resolve(
        mode=TriggerMode.TIME,
        impression_budget=None,
        slot_minutes=30,
        current=CURRENT_IMPRESSIONS,
    )

    assert resolved.mode is TriggerMode.TIME
    assert resolved.slot_minutes == 30


def test_switching_mode_alone_reuses_what_that_mode_was_set_to() -> None:
    """Flipping to time mode keeps the slot the test already carried.

    Both numbers are always stored, so switching back and forth does not lose
    the other mode's setting and force the user to retype it.
    """
    resolved = resolve(
        mode=TriggerMode.TIME,
        impression_budget=None,
        slot_minutes=None,
        current=CURRENT_IMPRESSIONS,
    )

    assert resolved.mode is TriggerMode.TIME
    assert resolved.slot_minutes == 45
    assert resolved.impression_budget == 2_000


def test_the_budget_is_accepted_when_switching_back_to_impressions() -> None:
    """A time test can be moved back onto impressions in one call."""
    resolved = resolve(
        mode=TriggerMode.IMPRESSIONS,
        impression_budget=1_500,
        slot_minutes=None,
        current=CURRENT_TIME,
    )

    assert resolved.mode is TriggerMode.IMPRESSIONS
    assert resolved.impression_budget == 1_500


def test_an_empty_edit_changes_nothing() -> None:
    """A PATCH with no fields is a no-op, not a reset to defaults."""
    resolved = resolve(mode=None, impression_budget=None, slot_minutes=None, current=CURRENT_TIME)

    assert resolved == CURRENT_TIME
