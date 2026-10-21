"""The diagnostic gate against a real PostgreSQL, with the policies installed.

The unit tests pin the four statements the gate issues. What they cannot show is
that those statements DO anything — that is a property of the server: a
read-only transaction refuses writes, and the policies confine a role that has
stopped being the table owner. Both are asserted here through the gate itself
rather than through hand-written SQL, so the thing under test is the thing a
probe will actually use.

The seeded tenants and the policy installation come from
``test_row_level_security``: one fixture, so a change to the policies is a
change both files see.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core import diagnostics
from src.core.diagnostics import DiagnosticGateError, diagnostic_session
from tests.integration.core.test_least_privilege_role import APP_ROLE
from tests.integration.core.test_row_level_security import (  # noqa: F401 - fixture import
    MINE,
    THEIRS,
    isolated,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch, engine: Any, isolated: None) -> None:  # noqa: F811
    """Point the gate at the tier's engine, its role, and the seeded tenant."""
    monkeypatch.setattr(diagnostics, "AsyncSessionLocal", async_sessionmaker(engine))
    monkeypatch.setattr(diagnostics, "RESTRICTED_ROLE", APP_ROLE)
    monkeypatch.setattr(diagnostics.settings, "diagnostic_workspace_id", str(MINE))


async def test_a_probe_with_no_where_clause_sees_one_кабинет(gated: None) -> None:
    """A query that asks for everything gets one workspace's rows.

    Deliberately unscoped: a probe that scoped its own SQL would pass with the
    gate removed, which is the one thing this must not do. This IS the shape the
    incident had — «select the busiest workspace and read it» — and here it can
    only ever select the allowed one.
    """
    async with diagnostic_session() as session:
        rows = (
            (
                await session.execute(
                    sa.text(
                        "SELECT workspace_id FROM monitoring.product_card "
                        "WHERE vendor_code = 'RLS-PROBE'"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert set(rows) == {MINE}
    assert THEIRS not in set(rows)


async def test_a_probe_cannot_write_even_what_its_role_may_write(gated: None) -> None:
    """The read-only half, which does not depend on grants at all.

    The application role is allowed to INSERT — it is the role the API writes
    with — so a gate resting on privileges alone would let this through. The
    transaction is what refuses it.
    """
    with pytest.raises(DBAPIError, match="read-only"):
        async with diagnostic_session() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO monitoring.product_card (nm_id, workspace_id, vendor_code) "
                    "VALUES (990000009, :ws, 'RLS-PROBE')"
                ),
                {"ws": str(MINE)},
            )


async def test_a_missing_role_is_a_refusal_rather_than_an_owner_session(
    monkeypatch: pytest.MonkeyPatch,
    engine: Any,
    isolated: None,  # noqa: F811
) -> None:
    """If the privileges cannot be dropped, no session is handed out.

    Without this the failure would be silent and total: `SET ROLE` to a role
    that does not exist leaves the connection as the OWNER, whom no policy
    binds — a probe would then read every workspace while believing it was pinned.
    """
    monkeypatch.setattr(diagnostics, "AsyncSessionLocal", async_sessionmaker(engine))
    monkeypatch.setattr(diagnostics, "RESTRICTED_ROLE", "role_that_does_not_exist")

    with pytest.raises(DiagnosticGateError):
        async with diagnostic_session():
            pass
