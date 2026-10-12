"""Unit tests for the page guards: one grant per page, and «any of» for the groups.

The routes' wiring is proved in the component tier; what is pinned here is the
rule the guard itself applies, without a request around it.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import PermissionDeniedError
from src.modules.organizations.deps import require_any_module, require_groups
from src.modules.organizations.models import ModuleKey
from src.modules.organizations.services.access import (
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
)


def _manager(*modules: str) -> OrganizationAccess:
    """A paid-up manager holding exactly ``modules``."""
    return OrganizationAccess(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=EffectiveRole.MANAGER,
        subscription=SubscriptionState.ACTIVE,
        is_primary_org=False,
        modules=modules,
    )


async def test_one_of_the_named_grants_is_enough() -> None:
    """«Any», not «all»: the second grant alone lets the caller in."""
    guard = require_any_module(ModuleKey.SUMMARY, ModuleKey.HEATMAP)
    access = _manager("heatmap")

    assert await guard(access) is access


async def test_none_of_the_named_grants_is_refused() -> None:
    """Grants elsewhere do not count."""
    guard = require_any_module(ModuleKey.SUMMARY, ModuleKey.HEATMAP)

    with pytest.raises(PermissionDeniedError):
        await guard(_manager("monitoring", "finreports"))


def test_a_guard_naming_no_grant_fails_at_import() -> None:
    """An empty set would quietly admit only owners — refused when it is built instead."""
    with pytest.raises(ValueError, match="at least one"):
        require_any_module()


@pytest.mark.parametrize("page", ["summary", "finreports", "heatmap", "advertising"])
async def test_every_page_with_the_group_filter_opens_the_groups(page: str) -> None:
    """The groups follow the pages that show them — P&L alone was the case that broke."""
    access = _manager(page)

    assert await require_groups(access) is access


async def test_monitoring_and_ab_tests_do_not_open_the_groups() -> None:
    """Neither page carries the filter, so neither reaches the groups."""
    with pytest.raises(PermissionDeniedError):
        await require_groups(_manager("monitoring", "ab_tests"))
