"""Unit tests for the access rules every guard in the codebase is built on.

Two decisions are pinned here, and both are the kind that is quiet when wrong:

* **where a subscription sits on the expiry ramp**, including the exact
  boundaries — an off-by-one at either end either locks a paying customer out a
  day early or hands a lapsed one an extra day;
* **what an ``OrganizationAccess`` permits**, which is the single place the
  platform role, the membership role and the subscription are combined.

Everything here is pure and takes its clock as an argument, so no time is
frozen and no database is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.modules.organizations.models import Subscription
from src.modules.organizations.services.access import (
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
    subscription_state,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _subscription(*, expires_in_days: float, grace_days: int = 3) -> Subscription:
    """A subscription expiring a given distance from :data:`NOW`.

    Built unattached to any session: these rules never read the database, and a
    test that needed one would be testing the repository instead.
    """
    return Subscription(
        organization_id=uuid.uuid4(),
        started_at=NOW - timedelta(days=30),
        expires_at=NOW + timedelta(days=expires_in_days),
        grace_days=grace_days,
    )


def _access(
    *,
    role: EffectiveRole,
    subscription: SubscriptionState = SubscriptionState.ACTIVE,
    is_primary_org: bool = False,
) -> OrganizationAccess:
    """An access record with the parts a test is not asserting about defaulted."""
    return OrganizationAccess(
        user_id=uuid.uuid4(),
        organization_id=None if role is EffectiveRole.USER else uuid.uuid4(),
        role=role,
        subscription=subscription,
        is_primary_org=is_primary_org,
    )


# --------------------------------------------------------------------------- #
# The expiry ramp
# --------------------------------------------------------------------------- #
def test_a_term_with_time_left_is_active() -> None:
    """The ordinary case: paid up, everything works."""
    assert subscription_state(_subscription(expires_in_days=5), now=NOW) is SubscriptionState.ACTIVE


def test_a_lapsed_term_inside_its_grace_window_still_works() -> None:
    """Renewal is a manual bank transfer between two humans in two countries.

    Locking a seller out of their own numbers while the payment is still
    clearing is a worse failure than a few extra days of access, so grace is
    full access — not a degraded mode.
    """
    lapsed = _subscription(expires_in_days=-2, grace_days=3)

    assert subscription_state(lapsed, now=NOW) is SubscriptionState.GRACE


def test_a_term_past_its_grace_window_falls_to_read_only() -> None:
    """Reads keep answering; writes stop. The data is the customer's own."""
    lapsed = _subscription(expires_in_days=-4, grace_days=3)

    assert subscription_state(lapsed, now=NOW) is SubscriptionState.READ_ONLY


def test_the_instant_of_expiry_is_already_grace_not_active() -> None:
    """The boundary is exclusive at the top: `expires_at` is when the term ENDS.

    Pinned because "expires at noon" reading as "still active at noon" is the
    off-by-one that gives every customer a free day and makes the grace window
    one day longer than it says it is.
    """
    assert subscription_state(_subscription(expires_in_days=0), now=NOW) is SubscriptionState.GRACE


def test_the_instant_grace_runs_out_is_already_read_only() -> None:
    """Same boundary rule at the other end, for the same reason."""
    exhausted = _subscription(expires_in_days=-3, grace_days=3)

    assert subscription_state(exhausted, now=NOW) is SubscriptionState.READ_ONLY


def test_a_zero_day_grace_drops_straight_to_read_only() -> None:
    """`grace_days = 0` is a valid setting and must not accidentally grant a day."""
    lapsed = _subscription(expires_in_days=-0.5, grace_days=0)

    assert subscription_state(lapsed, now=NOW) is SubscriptionState.READ_ONLY


def test_a_missing_subscription_is_read_only_rather_than_an_error() -> None:
    """Fail closed, and fail quietly.

    Activation writes the subscription in the same transaction as the
    organisation, so a tenant without one should be impossible. If it happens
    anyway, the safe reading is "may not write" — not a 500 on every request the
    tenant makes, and emphatically not full access.
    """
    assert subscription_state(None, now=NOW) is SubscriptionState.READ_ONLY


# --------------------------------------------------------------------------- #
# What an access record permits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_member_of_a_paid_up_tenant_may_write(role: EffectiveRole) -> None:
    """Both membership roles write inside their own organisation."""
    assert _access(role=role).can_write is True


def test_a_registered_user_with_no_organisation_may_not_write() -> None:
    """The `user` role is the state between registering and being let in."""
    assert _access(role=EffectiveRole.USER).can_write is False


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_read_only_tenant_may_not_write(role: EffectiveRole) -> None:
    """Past grace, every write and every WB refresh is refused."""
    access = _access(role=role, subscription=SubscriptionState.READ_ONLY)

    assert access.can_write is False


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_tenant_inside_its_grace_window_may_still_write(role: EffectiveRole) -> None:
    """Grace is full access — the whole point of having it."""
    access = _access(role=role, subscription=SubscriptionState.GRACE)

    assert access.can_write is True


def test_a_dev_writes_even_against_a_read_only_subscription() -> None:
    """Our own access must not depend on our own billing rows.

    A bad backfill or a mistyped expiry must not lock out the people who would
    fix it — which is exactly the position a dev gated on subscription state
    would be in.
    """
    access = _access(role=EffectiveRole.DEV, subscription=SubscriptionState.READ_ONLY)

    assert access.can_write is True


# --------------------------------------------------------------------------- #
# The internal-only surfaces
# --------------------------------------------------------------------------- #
def test_a_dev_sees_the_internal_features() -> None:
    assert _access(role=EffectiveRole.DEV).sees_internal_features is True


def test_a_member_of_the_primary_organisation_sees_the_internal_features() -> None:
    """Our own team reaches them through their organisation, not a dev role."""
    access = _access(role=EffectiveRole.MANAGER, is_primary_org=True)

    assert access.sees_internal_features is True


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_an_ordinary_tenant_does_not_see_the_internal_features(role: EffectiveRole) -> None:
    """They were built for one seller, against one seller's data and legal case.

    a document naming OUR company, computed from OUR settlement reports.
    """
    assert _access(role=role, is_primary_org=False).sees_internal_features is False


def test_a_user_with_no_organisation_sees_no_internal_features() -> None:
    """`is_primary_org` is False for a caller with no organisation at all."""
    assert _access(role=EffectiveRole.USER).sees_internal_features is False
