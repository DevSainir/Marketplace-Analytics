"""Extending a subscription by hand, after a renewal payment.

There is no renewal screen: payment is a bank transfer between two people, and
the extension that follows it is done by us, with ``scripts/extend_subscription.py``.
This module is the rule that script applies, kept out of it so the rule is
testable without a database.

The record of the change is not written here. A trigger on
``organizations.subscriptions`` writes it for every caller, this one included —
see :mod:`src.modules.organizations.models.subscription`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.modules.organizations.models import Subscription
from src.modules.organizations.repos import SubscriptionRepository


@dataclass(frozen=True, slots=True)
class Extension:
    """What an extension did: the term's end before and after."""

    previous_expires_at: datetime
    expires_at: datetime


def renewed_expiry(*, expires_at: datetime, grace_days: int, days: int, now: datetime) -> datetime:
    """Where a term paid for ``days`` more should end.

    A renewal that arrives while the service is still open — before expiry, or
    inside the grace window — continues the term from where it ended: the days
    the customer spent in grace were days of service, and the bank transfer
    taking a day longer must not hand them out a second time. One that arrives
    after the service has closed starts from now, since the days in between were
    days without access and cannot be charged for.

    Args:
        expires_at: The current end of the term.
        grace_days: The term's grace window.
        days: How many days were paid for.
        now: The instant of the renewal.

    Returns:
        The new end of the term.
    """
    still_open = now < expires_at + timedelta(days=grace_days)
    base = expires_at if still_open else now
    return base + timedelta(days=days)


async def extend_subscription(
    repo: SubscriptionRepository,
    subscription: Subscription,
    *,
    days: int,
    now: datetime | None = None,
) -> Extension:
    """Push ``subscription`` out by ``days`` paid days.

    Args:
        repo: The subscription repository on the caller's session.
        subscription: The term to extend.
        days: Paid days; must be positive.
        now: The instant of the renewal; defaults to the current UTC time.

    Returns:
        The term's end before and after.

    Raises:
        ValueError: ``days`` is not positive — a shortening is a different act
            and is not something to do by passing a negative number.
    """
    if days <= 0:
        raise ValueError(f"days must be positive, got {days}")
    previous = subscription.expires_at
    new_end = renewed_expiry(
        expires_at=previous,
        grace_days=subscription.grace_days,
        days=days,
        now=now or datetime.now(UTC),
    )
    await repo.extend(subscription, expires_at=new_end)
    return Extension(previous_expires_at=previous, expires_at=new_end)


__all__ = ["Extension", "extend_subscription", "renewed_expiry"]
