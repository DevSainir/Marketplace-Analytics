"""Unit tests for the access rules every guard in the codebase is built on.

Two decisions are pinned here, and both are the kind that is quiet when wrong:

* **where a subscription sits on the expiry ramp**, including the exact
  boundaries — an off-by-one at either end either locks a paying customer out a
  day early or hands a lapsed one an extra day, and since the ramp ends in a
  closed door rather than a read-only page, the first of those is now a
  customer who cannot open the app at all;
* **what an ``OrganizationAccess`` permits**, which is the single place the
  platform role, the membership role and the subscription are combined;
* **which tenants a background harvest may spend WB budget for** — the same
  question with no caller to ask it about, and the one whose wrong answer costs
  money rather than access.

Everything here is pure and takes its clock as an argument, so no time is
frozen and no database is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.core.exceptions import PermissionDeniedError
from src.modules.organizations.models import ModuleKey, Organization, Subscription
from src.modules.organizations.services.access import (
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
    harvestable_organization_ids,
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


def test_a_term_past_its_grace_window_expires() -> None:
    """Past grace the service closes — reads included, not just writes."""
    lapsed = _subscription(expires_in_days=-4, grace_days=3)

    assert subscription_state(lapsed, now=NOW) is SubscriptionState.EXPIRED


def test_the_instant_of_expiry_is_already_grace_not_active() -> None:
    """The boundary is exclusive at the top: `expires_at` is when the term ENDS.

    Pinned because "expires at noon" reading as "still active at noon" is the
    off-by-one that gives every customer a free day and makes the grace window
    one day longer than it says it is.
    """
    assert subscription_state(_subscription(expires_in_days=0), now=NOW) is SubscriptionState.GRACE


def test_the_instant_grace_runs_out_is_already_expired() -> None:
    """Same boundary rule at the other end, for the same reason."""
    exhausted = _subscription(expires_in_days=-3, grace_days=3)

    assert subscription_state(exhausted, now=NOW) is SubscriptionState.EXPIRED


def test_a_zero_day_grace_expires_immediately() -> None:
    """`grace_days = 0` is a valid setting and must not accidentally grant a day."""
    lapsed = _subscription(expires_in_days=-0.5, grace_days=0)

    assert subscription_state(lapsed, now=NOW) is SubscriptionState.EXPIRED


def test_a_missing_subscription_is_expired_rather_than_an_error() -> None:
    """Fail closed, and fail quietly.

    Activation writes the subscription in the same transaction as the
    organisation, so a tenant without one should be impossible. If it happens
    anyway, the safe reading is "has not paid" — not a 500 on every request the
    tenant makes, and emphatically not full access.
    """
    assert subscription_state(None, now=NOW) is SubscriptionState.EXPIRED


# --------------------------------------------------------------------------- #
# What an access record permits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_member_of_a_paid_up_tenant_may_write(role: EffectiveRole) -> None:
    """Both membership roles write inside their own organisation."""
    assert _access(role=role).can_write is True


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_paid_up_tenant_reaches_the_service(role: EffectiveRole) -> None:
    """The positive half of the paywall, so the property cannot answer False always."""
    assert _access(role=role).has_access is True


def test_a_registered_user_with_no_organisation_may_not_write() -> None:
    """The `user` role is the state between registering and being let in."""
    assert _access(role=EffectiveRole.USER).can_write is False


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_an_expired_tenant_reaches_nothing_at_all(role: EffectiveRole) -> None:
    """Past grace the service closes: not read-only, shut.

    This replaced a read-only landing on 2026-09-09. The pair of assertions is
    the whole change — `has_access` is the new one, and `can_write` staying
    False is what says the narrower guard did not quietly widen when the
    broader one took over its job.
    """
    access = _access(role=role, subscription=SubscriptionState.EXPIRED)

    assert access.has_access is False
    assert access.can_write is False


@pytest.mark.parametrize("role", [EffectiveRole.OWNER, EffectiveRole.MANAGER])
def test_a_tenant_inside_its_grace_window_may_still_write(role: EffectiveRole) -> None:
    """Grace is full access — the whole point of having it.

    Unchanged by the move to a paywall: the days that protect a clearing bank
    transfer are exactly the days that must not feel any different.
    """
    access = _access(role=role, subscription=SubscriptionState.GRACE)

    assert access.has_access is True
    assert access.can_write is True


def test_a_dev_is_exempt_from_an_expired_subscription() -> None:
    """Our own access must not depend on our own billing rows.

    A bad backfill or a mistyped expiry must not lock out the people who would
    fix it — which is exactly the position a dev gated on subscription state
    would be in. That was true when the state cost writes; it matters more now
    that it costs the whole service.
    """
    access = _access(role=EffectiveRole.DEV, subscription=SubscriptionState.EXPIRED)

    assert access.has_access is True
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


# --------------------------------------------------------------------------- #
# Who may issue activation codes
# --------------------------------------------------------------------------- #
def test_a_dev_may_issue_codes() -> None:
    """A dev issues codes whatever organisation they belong to."""
    assert _access(role=EffectiveRole.DEV, is_primary_org=False).can_issue_codes is True


def test_the_owner_of_the_primary_organisation_may_issue_codes() -> None:
    """The person who takes the money hands out what it buys."""
    access = _access(role=EffectiveRole.OWNER, is_primary_org=True)

    assert access.can_issue_codes is True


def test_a_manager_of_the_primary_organisation_may_not_issue_codes() -> None:
    """Seeing our internal features is not the same as selling paid accounts."""
    access = _access(role=EffectiveRole.MANAGER, is_primary_org=True)

    assert access.can_issue_codes is False


def test_a_customers_owner_may_not_issue_codes() -> None:
    """An owner of any other organisation would be minting free accounts."""
    access = _access(role=EffectiveRole.OWNER, is_primary_org=False)

    assert access.can_issue_codes is False


# --------------------------------------------------------------------------- #
# A guest with no company of their own
# --------------------------------------------------------------------------- #
def _guest(*, organization_id: uuid.UUID | None = None) -> OrganizationAccess:
    """A head; with no organisation unless one is given."""
    return OrganizationAccess(
        user_id=uuid.uuid4(),
        organization_id=organization_id,
        role=EffectiveRole.USER if organization_id is None else EffectiveRole.MANAGER,
        subscription=SubscriptionState.EXPIRED,
        is_primary_org=False,
        is_head=True,
    )


def test_a_head_with_no_organisation_is_let_in_to_read() -> None:
    """The grant is the whole point: nothing of their own to pay for, nothing to write."""
    guest = _guest()

    assert (guest.is_guest_only, guest.has_access, guest.can_write) == (True, True, False)


@pytest.mark.parametrize("module", list(ModuleKey))
def test_a_head_with_no_organisation_reaches_every_section(module: ModuleKey) -> None:
    """Which кабинет is decided by the grant; inside it, everything is readable."""
    assert _guest().can_reach(module) is True


def test_a_head_with_no_organisation_has_no_tenant_of_their_own() -> None:
    """A route that needs the caller's organisation refuses instead of scoping to None."""
    with pytest.raises(PermissionDeniedError):
        _ = _guest().tenant_id


def test_a_plain_account_with_no_organisation_is_still_shut_out() -> None:
    """Without the head role nothing changes for a bare registration."""
    access = _access(role=EffectiveRole.USER, subscription=SubscriptionState.EXPIRED)

    assert (access.is_guest_only, access.has_access) == (False, False)


def test_a_head_inside_a_lapsed_company_is_not_a_guest_only() -> None:
    """Their own company's paywall still applies to them."""
    guest = _guest(organization_id=uuid.uuid4())

    assert (guest.is_guest_only, guest.has_access) == (False, False)


# --------------------------------------------------------------------------- #
# The harvest gate — the same paywall, asked by a task with no caller
# --------------------------------------------------------------------------- #
def _organization(*, is_primary: bool = False) -> Organization:
    """An unattached organisation row, for the pure fan-out rule."""
    return Organization(id=uuid.uuid4(), name="ООО Тест", is_primary=is_primary)


def test_a_paid_up_tenant_is_harvested() -> None:
    """The ordinary case, pinned so the gate cannot answer «nobody» by accident."""
    org = _organization()
    term = _subscription(expires_in_days=5)
    term.organization_id = org.id

    assert harvestable_organization_ids([org], [term], now=NOW) == frozenset({org.id})


def test_a_tenant_inside_its_grace_window_is_still_harvested() -> None:
    """Grace is full access, and a harvest is part of what full access buys.

    A gap in WB's advertising and cluster history cannot be backfilled, so a
    harvest stopped during the days a bank transfer is clearing would leave a
    permanent hole in the data of a customer who did pay.
    """
    org = _organization()
    term = _subscription(expires_in_days=-2, grace_days=3)
    term.organization_id = org.id

    assert harvestable_organization_ids([org], [term], now=NOW) == frozenset({org.id})


def test_an_expired_tenant_is_not_harvested() -> None:
    """The point of the gate: no WB budget is spent for a tenant who cannot log in.

    Before this, an expired tenant reached nothing in the app while the nightly
    harvest kept calling WB on its tokens — a paywall with a bill attached, paid
    out of a rate budget shared with the customers who are paying.
    """
    org = _organization()
    term = _subscription(expires_in_days=-4, grace_days=3)
    term.organization_id = org.id

    assert harvestable_organization_ids([org], [term], now=NOW) == frozenset()


def test_a_tenant_with_no_subscription_row_is_not_harvested() -> None:
    """Fail closed, and here that means fail cheap.

    Everywhere else a missing row costs the tenant access. Here it would cost
    us money, so the unmatched case must deny rather than default to allow.
    """
    assert harvestable_organization_ids([_organization()], [], now=NOW) == frozenset()


def test_our_own_organisation_is_harvested_whatever_its_billing_says() -> None:
    """The task-side twin of the dev exemption.

    A bad backfill or a mistyped expiry on OUR row must not stop OUR data
    collection — and unlike access, a stopped harvest is not recoverable by
    fixing the row afterwards: WB serves no history for the advertising and
    cluster surfaces, so the days lost stay lost.
    """
    ours = _organization(is_primary=True)
    lapsed = _subscription(expires_in_days=-40, grace_days=3)
    lapsed.organization_id = ours.id

    assert harvestable_organization_ids([ours], [lapsed], now=NOW) == frozenset({ours.id})


def test_one_lapsed_tenant_does_not_stop_the_others() -> None:
    """The fan-out drops a seller, never the run.

    Worth pinning because the failure it guards against is silent in both
    directions: a gate that dropped everyone would look like a harvest that
    found nothing, and a gate that dropped no one would look like it working.
    """
    paid, lapsed = _organization(), _organization()
    paid_term = _subscription(expires_in_days=5)
    paid_term.organization_id = paid.id
    lapsed_term = _subscription(expires_in_days=-9, grace_days=3)
    lapsed_term.organization_id = lapsed.id

    harvestable = harvestable_organization_ids([paid, lapsed], [paid_term, lapsed_term], now=NOW)

    assert harvestable == frozenset({paid.id})
