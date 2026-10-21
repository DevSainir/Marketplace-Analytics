"""The gate every production probe has to go through.

The worker container connects as the table owner, so row-level security does
not apply to it. An ad-hoc probe run there can pick "the workspace with the
most rows" and print a paying customer's revenue into a transcript. Nothing
refuses it, because nothing is asked.

What is pinned here is the shape that makes that impossible by accident: the
session is read-only, it drops the owner's privileges, it binds one workspace,
and there is no parameter through which a caller can name a different one.

Unit tier: the seam is the four statements the gate issues, and a fake session
records them in order.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest

from src.core import diagnostics
from src.core.diagnostics import (
    DIAGNOSTIC_WORKSPACE,
    DiagnosticGateError,
    diagnostic_session,
    diagnostic_workspace,
)

pytestmark = pytest.mark.unit


class _FakeSession:
    """Records the statements the gate issues, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, Any] | None] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.statements.append(str(statement).strip())
        self.params.append(params)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    """Swap the real session factory for a recorder."""
    fake = _FakeSession()
    monkeypatch.setattr(diagnostics, "AsyncSessionLocal", lambda: fake)
    return fake


async def test_the_transaction_is_read_only_before_anything_runs_in_it(
    session: _FakeSession,
) -> None:
    """READ ONLY comes first, because PostgreSQL will not accept it later.

    It is also the half of the gate that does not depend on grants: whatever the
    role may do, the server refuses every write and every DDL in this
    transaction.
    """
    async with diagnostic_session():
        pass

    assert session.statements[0] == "SET TRANSACTION READ ONLY"


async def test_the_owners_privileges_are_dropped(session: _FakeSession) -> None:
    """Row-level security does not apply to the table owner, and the worker IS it.

    Without this the policies are inert and the pin below is decoration.
    """
    async with diagnostic_session():
        pass

    assert "SET LOCAL ROLE marketplace_app" in session.statements


async def test_the_one_allowed_кабинет_is_bound(session: _FakeSession) -> None:
    """The tenant is announced the way a request announces it."""
    async with diagnostic_session():
        pass

    assert session.params[-1] == {"value": str(DIAGNOSTIC_WORKSPACE)}


async def test_a_caller_cannot_name_a_different_кабинет() -> None:
    """There is no parameter to pass one through.

    The mistake to prevent is choosing a workspace, so the gate does not offer the choice —
    a default that can be overridden is a default that will be.
    """
    assert inspect.signature(diagnostic_session).parameters == {}


async def test_a_role_name_that_is_not_an_identifier_is_refused(
    session: _FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The role is interpolated (PostgreSQL takes no parameter there), so it is checked.

    Fails closed: no session at all beats a session whose pinning half-happened.
    """
    monkeypatch.setattr(diagnostics, "RESTRICTED_ROLE", "marketplace_app; DROP SCHEMA public")

    with pytest.raises(DiagnosticGateError):
        async with diagnostic_session():
            pass

    assert session.statements == []


def test_an_unreadable_allowlist_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed override raises rather than falling back to "no restriction"."""
    monkeypatch.setattr(
        diagnostics.settings, "diagnostic_workspace_id", "not-a-uuid", raising=False
    )

    with pytest.raises(DiagnosticGateError):
        diagnostic_workspace()


def test_the_default_needs_no_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unconfigured means «Демо», never «anything».

    A gate that only worked on a box somebody had configured would be off
    exactly where a one-off probe gets written — in a shell, in a hurry.
    """
    monkeypatch.setattr(diagnostics.settings, "diagnostic_workspace_id", "", raising=False)

    assert diagnostic_workspace() == DIAGNOSTIC_WORKSPACE
    assert isinstance(DIAGNOSTIC_WORKSPACE, uuid.UUID)
