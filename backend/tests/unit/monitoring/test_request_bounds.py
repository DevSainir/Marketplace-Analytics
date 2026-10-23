"""A caller must not be able to ask for unbounded work by sending a long list.

The window ceiling (``resolve_window``) bounded the days the
server would SELECT, and bounded nothing about the days a caller could ASSERT:
the matrix preview and save endpoints take the whole working copy from the
client and recompute every cell of it. The SKU lists had no ceiling at all.

The caps live in ``monitoring/constants.py`` so the schema and the service agree
on one number — a matrix body wide enough to hold a window the analysis
endpoints would refuse is not a legitimate request.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.core.exceptions import ValidationError
from src.modules.monitoring.constants import (
    MAX_MATRIX_DAYS,
    MAX_NM_IDS_PER_REQUEST,
    MAX_WINDOW_DAYS,
)
from src.modules.monitoring.schemas.matrix import MatrixBaseState, MatrixDayBase
from src.modules.monitoring.schemas.pins import PinReorderRequest
from src.modules.monitoring.services.analytics.window import resolve_window


def _days(count: int) -> list[MatrixDayBase]:
    """Build ``count`` day columns starting from a fixed date."""
    start = date(2026, 1, 1)
    return [MatrixDayBase(day=start + timedelta(days=i)) for i in range(count)]


def test_a_matrix_body_may_not_claim_more_days_than_a_window_can_hold() -> None:
    """The working copy is a REQUEST body, so its length is attacker-chosen.

    Every cell of whatever arrives is recomputed server-side, which makes an
    uncapped list arithmetic anyone can order by the megabyte.
    """
    with pytest.raises(PydanticValidationError, match="too_long"):
        MatrixBaseState(days=_days(MAX_MATRIX_DAYS + 1))


def test_the_widest_legitimate_window_still_fits() -> None:
    """The cap must not reject a working copy the app itself would produce."""
    state = MatrixBaseState(days=_days(MAX_MATRIX_DAYS))

    assert len(state.days) == MAX_MATRIX_DAYS


def test_the_matrix_cap_and_the_window_ceiling_agree() -> None:
    """The two bounds are one number, so they cannot drift apart.

    Were the body cap the smaller, the widest window a caller may legitimately
    request would come back as a body they could not send again.
    """
    end = date(2026, 12, 31)
    widest = resolve_window(end - timedelta(days=MAX_WINDOW_DAYS), end)

    assert (widest[1] - widest[0]).days + 1 == MAX_MATRIX_DAYS


def test_a_window_past_the_ceiling_is_still_refused() -> None:
    """Sharing the constant must not have loosened the original guard."""
    end = date(2026, 12, 31)

    with pytest.raises(ValidationError, match="cannot exceed"):
        resolve_window(end - timedelta(days=MAX_WINDOW_DAYS + 1), end)


def test_a_pin_reorder_may_not_carry_an_unbounded_sku_list() -> None:
    """The chip row is a handful of SKUs; the endpoint accepted any number."""
    with pytest.raises(PydanticValidationError, match="too_long"):
        PinReorderRequest(nm_ids=list(range(MAX_NM_IDS_PER_REQUEST + 1)))


def test_a_realistic_pin_row_is_unaffected() -> None:
    """The cap sits far above any real chip row."""
    request = PinReorderRequest(nm_ids=[1, 2, 3])

    assert request.nm_ids == [1, 2, 3]
