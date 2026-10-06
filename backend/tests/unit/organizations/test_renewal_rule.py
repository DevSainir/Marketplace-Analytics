"""Where a hand-made renewal puts the end of the term.

Pinned because both wrong answers are quiet: continuing a long-closed term from
its old end hands the customer back days that already passed without service
(they pay for two weeks and get four days), and restarting a term still in
grace from "now" gives away the grace days a second time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.organizations.services.renewal import extend_subscription, renewed_expiry

EXPIRES = datetime(2026, 10, 5, 6, 27, tzinfo=UTC)


def test_a_term_renewed_before_expiry_continues_from_its_end() -> None:
    """Paying early never costs the customer the days they had left."""
    now = EXPIRES - timedelta(days=2)

    result = renewed_expiry(expires_at=EXPIRES, grace_days=3, days=14, now=now)

    assert result == EXPIRES + timedelta(days=14)


def test_a_term_renewed_in_grace_continues_from_its_end() -> None:
    """The grace days were days of service, so they are not handed out again."""
    now = EXPIRES + timedelta(days=1, hours=4)

    result = renewed_expiry(expires_at=EXPIRES, grace_days=3, days=14, now=now)

    assert result == EXPIRES + timedelta(days=14)


def test_a_term_renewed_after_the_service_closed_starts_from_now() -> None:
    """Days without access are not charged for."""
    now = EXPIRES + timedelta(days=10)

    result = renewed_expiry(expires_at=EXPIRES, grace_days=3, days=14, now=now)

    assert result == now + timedelta(days=14)


async def test_a_non_positive_extension_is_refused() -> None:
    """Shortening a term is a different act, not a negative renewal."""
    with pytest.raises(ValueError, match="positive"):
        await extend_subscription(None, None, days=0)  # type: ignore[arg-type]
