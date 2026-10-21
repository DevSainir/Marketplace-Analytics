"""The access guards every protected route in every module is built from.

Domain decisions rather than infrastructure — what a role means, what a
lapsed subscription costs, which page a manager was given — which is why they
live in this module and not in ``core/deps.py``.

The guards compose, and each one is strictly narrower than the last:

``CurrentAccess``
    Resolve the caller. No requirement beyond a valid token; a registered
    account with no organisation gets through, which is what the activation and
    invitation routes need.
``MemberAccess``
    Require an organisation AND a subscription that has not fallen past its
    grace window. This is the one that closes the platform — to the ``user``
    role, and to a tenant that has stopped paying. It is on every data router
    in the application, which is what makes the paywall total rather than a
    per-route decision somebody has to remember.
``WritingAccess``
    Require all of the above AND a role that writes. On every route that
    changes something or spends WB budget. Narrower than ``MemberAccess`` only
    for a manager the owner set to read-only — the subscription half is already
    decided one rung down.
``OwnerAccess``
    Require ``owner`` (or ``dev``). Workspaces, tokens, members, billing.

``InternalAccess`` is separate rather than a fifth rung: it is not more
authority inside a tenant, it is a different question — whether this caller is
one of *us*."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
from src.core.exceptions import PermissionDeniedError
from src.core.logcontext import bind_tenant
from src.modules.organizations.models import GROUP_MODULES
from src.modules.organizations.services import (
    AccessLevel,
    EffectiveRole,
    ModuleKey,
    OrganizationAccess,
    resolve_access,
)
from src.modules.users.contract import CurrentUser


async def get_current_access(session: DbSession, user: CurrentUser) -> OrganizationAccess:
    """Resolve the caller's role, tenant and subscription state.

    Depends on ``CurrentUser`` rather than on the token's user id alone,
    because the platform role has to be read from the LIVE row: a revoked dev
    role must take effect on the next request, not when the access token
    happens to expire.
    """
    access = await resolve_access(session, user_id=user.id, platform_role=user.role)
    # From here the request's log lines name the tenant too.
    # Bound here rather than in the middleware because this is the first point
    # the tenant is KNOWN — it comes from a membership lookup, not the token.
    bind_tenant(access.organization_id)
    return access


#: The caller's resolved access. No requirement beyond a valid token.
CurrentAccess = Annotated[OrganizationAccess, Depends(get_current_access)]


async def require_member(access: CurrentAccess) -> OrganizationAccess:
    """Require an organisation whose subscription has not run out.

    Two refusals, one guard, because they are the same question — *may this
    caller reach the product at all* — and separating them is how a route ends
    up covered by one and not the other.

    **Membership.** This is what closes the platform to a bare registered
    account. Registration is open, so without it every new signup would land
    inside somebody's data; with it, a fresh account can reach exactly two
    things — activation and its own pending invitations.

    **Payment.** Past the grace window the service closes completely: no reads
    either. This was a read-only landing until 2026-09-09, on the reasoning
    that the data is the customer's own and locking them out of it is a hostage
    position. It is now a paywall — an expired tenant that keeps its dashboards
    has no deadline, and the renewal it was supposed to prompt never comes. The
    three grace days are still there, and are still where a clearing bank
    transfer is protected; what follows them is now a door rather than a
    dimmer.

    A dev with no organisation of their own is deliberately NOT let through
    here: the routes behind this guard are all tenant-scoped, and there is no
    tenant to scope them to. Devs read a customer's data by belonging to an
    organisation, not by bypassing the concept — and a dev inside a lapsed
    tenant still gets through, so our own billing rows cannot lock out the
    people who would fix them.

    The one caller let through with no organisation is a head with nothing of
    their own (:attr:`OrganizationAccess.is_guest_only`): they reach only the
    workspaces a dev granted them, read-only, and every route that needs their
    own organisation still refuses them through ``tenant_id``.

    ``/me``, ``/activate`` and ``/invitations/mine`` sit in front of this guard
    on ``CurrentAccess``, which is what leaves a blocked caller something to
    load: the SPA reads the state from ``/me`` and draws the paywall instead of
    an app full of failed requests.

    Raises:
        PermissionDeniedError: No membership, or a subscription past grace.
    """
    if access.organization_id is None and not access.is_guest_only:
        raise PermissionDeniedError(
            "Аккаунт не привязан к организации. Введите ключ активации или примите приглашение."
        )
    if not access.has_access:
        # Checked AFTER the membership: an account with nowhere to be is not
        # behind on a payment, and telling them to renew sends them to support
        # with the wrong question.
        raise PermissionDeniedError(
            "Подписка истекла — доступ к сервису закрыт. Продлите подписку, чтобы вернуть доступ."
        )
    return access


MemberAccess = Annotated[OrganizationAccess, Depends(require_member)]


async def require_writer(access: MemberAccess) -> OrganizationAccess:
    """Require a member who may change things.

    Applied to everything that changes state or spends WB rate budget. Since
    2026-09-09 the subscription half of this is already settled by
    :func:`require_member` — a lapsed tenant never reaches a route at all — so
    in practice this rung narrows one caller: the manager their owner granted
    the section at ``read_only``.

    The subscription check stays anyway. It costs a comparison, and a guard
    that quietly depends on a rung below it being applied is a guard that stops
    holding the day somebody wires a writing route past that rung.

    Raises:
        PermissionDeniedError: A read-only manager, or (defensively) a
            subscription past grace.
    """
    if not access.can_write:
        # Two different reasons land here and the person can act on only one of
        # them. An owner whose term lapsed can renew; a manager the owner set to
        # read-only cannot, and telling them to renew sends them to support with
        # the wrong question.
        if access.access_level is AccessLevel.READ_ONLY and access.role is EffectiveRole.MANAGER:
            raise PermissionDeniedError(
                "Доступ только для чтения — изменения вносит владелец организации."
            )
        raise PermissionDeniedError(
            "Подписка истекла — доступ к сервису закрыт. Продлите подписку, чтобы вернуть доступ."
        )
    return access


WritingAccess = Annotated[OrganizationAccess, Depends(require_writer)]


def require_any_module(
    *modules: ModuleKey,
) -> Callable[[OrganizationAccess], Awaitable[OrganizationAccess]]:
    """Build the guard that admits callers granted at least one of ``modules``.

    Declared once on each module's own ``APIRouter`` rather than on its
    routes, which is what makes it hold: a route added tomorrow inherits the
    grant instead of having to remember it, and there is exactly one line per
    module to read when asking what a surface is protected by.

    It gates reachability, not writing — ``require_writer`` already refuses a
    read-only manager, and stacking the two means a manager needs the module
    AND the level to change anything in it.

    "Any", not "all": a page is one grant, and the only thing shared between
    pages — the groups — opens with whichever of its pages the caller holds.

    Args:
        modules: The surfaces any one of which lets the caller in.

    Returns:
        A FastAPI dependency.
    """
    if not modules:
        # An empty set would admit nobody but owners and devs, silently — a
        # guard built wrong must fail at import, not at somebody's request.
        raise ValueError("require_any_module needs at least one module")

    async def _guard(access: MemberAccess) -> OrganizationAccess:
        if not any(access.can_reach(module) for module in modules):
            # Deliberately says the access is missing rather than that the
            # module is: "no such section" would be a lie the person cannot
            # act on, and they need to know who to ask.
            raise PermissionDeniedError(
                "Раздел недоступен для вашей учётной записи. Доступ выдаёт владелец организации."
            )
        return access

    return _guard


def require_module(
    module: ModuleKey,
) -> Callable[[OrganizationAccess], Awaitable[OrganizationAccess]]:
    """Build the guard that admits callers granted one product surface."""
    return require_any_module(module)


#: One per page of the header. The bare callables are what a module's router
#: puts in ``dependencies=[...]``; the annotated forms are for a route that also
#: wants the resolved access object in its signature.
require_monitoring = require_module(ModuleKey.MONITORING)
require_finreports = require_module(ModuleKey.FINREPORTS)
require_ab_tests = require_module(ModuleKey.AB_TESTS)
require_advertising = require_module(ModuleKey.ADVERTISING)
require_summary = require_module(ModuleKey.SUMMARY)
require_heatmap = require_module(ModuleKey.HEATMAP)
#: The groups are a control on four pages rather than a page of their own, so
#: whoever holds one of those pages reads them — and edits them, at the writing
#: level — the same as on the page itself.
require_groups = require_any_module(*GROUP_MODULES)

MonitoringAccess = Annotated[OrganizationAccess, Depends(require_monitoring)]
FinreportsAccess = Annotated[OrganizationAccess, Depends(require_finreports)]
AbTestsAccess = Annotated[OrganizationAccess, Depends(require_ab_tests)]


async def require_owner(access: MemberAccess) -> OrganizationAccess:
    """Require the organisation's owner (or a dev).

    Guards the things that change who and what the organisation IS: its
    workspaces, its WB credentials, its members, its name.

    Raises:
        PermissionDeniedError: The caller is a manager.
    """
    if access.role not in (EffectiveRole.OWNER, EffectiveRole.DEV):
        raise PermissionDeniedError("Действие доступно только владельцу организации.")
    return access


OwnerAccess = Annotated[OrganizationAccess, Depends(require_owner)]


async def require_internal(access: CurrentAccess) -> OrganizationAccess:
    """Require a caller who is one of us.

    seller, against our own data and our own legal case. Reachable by devs
    and by members of the primary organisation, by nobody else.

    Not built on :data:`MemberAccess`: a dev without an organisation still gets
    through, because these routes are ours rather than a tenant's.

    Raises:
        PermissionDeniedError: Anyone else. Phrased as "not available" rather
            than "you are not us", since to a customer this feature does not
            exist.
    """
    if not access.sees_internal_features:
        raise PermissionDeniedError("Раздел недоступен.")
    return access


InternalAccess = Annotated[OrganizationAccess, Depends(require_internal)]


async def require_dev(access: CurrentAccess) -> OrganizationAccess:
    """Require the platform ``dev`` role (activation-code administration).

    Raises:
        PermissionDeniedError: Anyone else.
    """
    if access.role is not EffectiveRole.DEV:
        raise PermissionDeniedError("Действие доступно только разработчику.")
    return access


DevAccess = Annotated[OrganizationAccess, Depends(require_dev)]


async def require_code_issuer(access: CurrentAccess) -> OrganizationAccess:
    """Require a dev, or the owner of the primary organisation.

    Narrower than :data:`InternalAccess`, which also admits our managers: a
    code is a paid account handed out, and that is the owner's call.

    Raises:
        PermissionDeniedError: Anyone else.
    """
    if not access.can_issue_codes:
        raise PermissionDeniedError("Действие недоступно.")
    return access


CodeIssuerAccess = Annotated[OrganizationAccess, Depends(require_code_issuer)]
